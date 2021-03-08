import datetime
import fire
import json
from ratelimit import limits, sleep_and_retry
import requests
import sys
import time

HEADERS = {
    'content-type': "application/json",
    'cache-control': "no-cache"
}

API_URL = 'https://admin.zscalerthree.net/api/v1'
AUTH_ENDPOINT = 'authenticatedSession'
AUTH_URL = '/'.join([API_URL, AUTH_ENDPOINT])


def formatted_datetime():
    wo_ms = str(datetime.datetime.now()).split('.')[0]
    day, time_str = tuple(wo_ms.split(' '))
    return "_".join([day.replace("-", ""), time_str.replace(":", "")])


# keep chunks at 400 for zscaler API
def chunks_of_len(list_to_chunk, chunk_len=400):
    n = max(1, chunk_len)
    return (list_to_chunk[i:i + n] for i in range(0, len(list_to_chunk), n))


def chunks_n_eq(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


class LoginData:
    def __init__(self, usr, pwd, api_key):
        self.username = usr
        self.password = pwd
        self.apiKey, self.timestamp = LoginData.obfuscate_api_key(api_key)

    def to_json(self):
        return json.dumps(self,
                          default=lambda o: o.__dict__,
                          sort_keys=True, indent=4)

    @staticmethod
    def obfuscate_api_key(api_key):
        seed = api_key
        now = int(time.time() * 1000)
        n = str(now)[-6:]
        r = str(int(n) >> 1).zfill(6)
        key = ""
        for i in range(0, len(str(n)), 1):
            key += seed[int(str(n)[i])]
        for j in range(0, len(str(r)), 1):
            key += seed[int(str(r)[j]) + 2]

        print("Timestamp:", now, "\tKey", key)
        return key, now


class UserManager:
    SECONDS_IN_HOUR = 60 * 60

    DEPARTMENTS_ENDPOINT = 'departments'
    DEPARTMENTS_ENDPOINT_URL = '/'.join([API_URL, DEPARTMENTS_ENDPOINT])
    GROUPS_ENDPOINT = 'groups'
    GROUPS_ENDPOINT_URL = '/'.join([API_URL, GROUPS_ENDPOINT])
    USERS_ENDPOINT = 'users'
    USERS_ENDPOINT_URL = '/'.join([API_URL, USERS_ENDPOINT])
    USER_PUT_ENDPOINT = '/'.join([API_URL, USERS_ENDPOINT, '{}'])

    def __init__(self):
        self._session = None
        self._departments = None
        self._groups_dict = None
        self._groups_list = None
        self._page_size = 500

    def __del__(self):
        self._session.close()

    # move this to class aggregating managers
    def start_auth_session(self, u, p, k):
        login_data = LoginData(usr=u, pwd=p, api_key=k)
        self._session = requests.session()
        auth_result = self._session.post(url=AUTH_URL,
                                         headers=HEADERS,
                                         data=login_data.to_json())
        print('AUTH RESULT code {0}'.format(auth_result.status_code))
        if auth_result.status_code != 200:
            print("Authentication failed, exiting!")
            sys.exit(-1)

    @sleep_and_retry
    @limits(calls=1, period=1)
    def get_departments(self):
        get_departments_results = self._session.get(url=self.DEPARTMENTS_ENDPOINT_URL,
                                                    headers=HEADERS)
        self._departments = json.loads(get_departments_results.content.decode('utf-8'))

    @sleep_and_retry
    @limits(calls=1, period=1)
    def get_groups(self):
        get_groups_results = self._session.get(url=self.GROUPS_ENDPOINT_URL,
                                               headers=HEADERS)
        self._groups_list = json.loads(get_groups_results.content.decode('utf-8'))
        self._groups_dict = {g['name']: g for g in self._groups_list}

    @property
    def groups(self):
        if self._groups_dict is None:
            self.get_groups()
        return self._groups_dict

    @property
    def groups_list(self):
        if self._groups_list is None:
            self.get_groups()
        return self._groups_list

    @property
    def departments(self):
        if self._departments is None:
            self.get_departments()
        return self._departments

    def _validate_groups(self, input_groups):
        if not set(input_groups).issubset(self.groups.keys()):
            print('ERROR: one or more of input groups is not added in ZIA hosted DB')
            sys.exit(1)

    def _validate_departments(self, input_department):
        existing_dep_names = set([dep['name'] for dep in self.departments])
        if input_department not in existing_dep_names:
            print('ERROR: input department is not added in ZIA hosted DB')
            sys.exit(1)

    def initialize_n_validate_data(self, input_department, input_groups):
        self._validate_departments(input_department=input_department)
        self._validate_groups(input_groups=input_groups)

    def get_and_modify_users_from_api(self, input_department, groups, start, end):
        page_number = start
        group_index = 0
        while True:
            if page_number > end:
                break
            # five 500 long user pages per group -> 2.5k users per group
            if page_number % 5 == 0:
                if group_index < (len(groups) - 1):
                    group_index += 1
            group_to_add_name = groups[group_index]
            users_data = self.get_users_page_to_modify(input_department=input_department,
                                                       page_number=page_number)
            if len(users_data) == 0:
                break
            for user in users_data:
                try:
                    self.update_user_with_group(user_obj=user, group_to_add_name=group_to_add_name)
                except Exception as exception:
                    print('EXCEPTION ON PUT USER {} UPDATE ATTEMPT'.format(exception))
                    continue
            page_number += 1

    @sleep_and_retry
    @limits(calls=1000, period=SECONDS_IN_HOUR)
    def update_user_with_group(self, user_obj, group_to_add_name):
        group_to_add = self.groups[group_to_add_name]
        if group_to_add not in user_obj['groups']:
            user_obj['groups'].append(group_to_add)
            put_user_result = self._session.put(url=self.USER_PUT_ENDPOINT.format(user_obj['id']),
                                                headers=HEADERS,
                                                json=user_obj)
            print('USER PUT UPDATE RESULT: {}'.format(put_user_result.status_code))
        else:
            print('USER {} ALREADY IN GROUP: {}'.format(user_obj['name'], str(group_to_add)))

    @sleep_and_retry
    @limits(calls=1, period=1)
    def get_users_page_to_modify(self, input_department, page_number=1):
        pagination = '&page={page_no}&pageSize={page_size}'.format(page_no=page_number, page_size=self._page_size)
        paginated_url = '/'.join([API_URL, self.USERS_ENDPOINT, '?dept=' + input_department + pagination])
        get_users_result = self._session.get(url=paginated_url, headers=HEADERS)
        users = json.loads(get_users_result.content.decode('utf-8'))
        return users

    @sleep_and_retry
    @limits(calls=1000, period=SECONDS_IN_HOUR)
    def add_test_user(self, user_to_copy):
        user_name = user_to_copy['login_name'].split('@')[0]
        new_user = {
            'name': 'tu_{}'.format(user_name),
            'email': '{}@bgriner.zscalerthree.net'.format(user_name),
            'department': {'id': 21826133, 'name': 'test_dep_1'},
            'groups': [{'id': 21826124, 'name': 'group_mod_test_1'}],
            'comments': 'asdas',
            'adminUser': False,
            'password': '1DPUA2UDPA3*'
        }
        post_user_result = self._session.post(url=self.USERS_ENDPOINT_URL,
                                              headers=HEADERS,
                                              json=new_user)
        print('TEST USER POST RESULT: {}'.format(post_user_result.status_code))

    def group_to_dept(self, u, p, k, start=1, end=10000, psize=None, file_path=None):
        if psize is not None:
            self._page_size = psize
        self.start_auth_session(u=u, p=p, k=k)
        dept_name = self.get_department_user_selection()
        input_groups = self.get_groups_user_selection()
        if file_path is None:
            self.get_and_modify_users_from_api(input_department=dept_name,
                                               groups=input_groups,
                                               start=start,
                                               end=end)

    def get_groups_user_selection(self):
        for idx, group in enumerate(self.groups_list):
            print('{}: {}'.format(idx, group))
        input_str = input('Choose groups by providing comma separted indices:')
        group_indices = input_str.split(',')
        input_groups = []
        for str_idx in group_indices:
            idx = int(str_idx)
            input_groups.append(self.groups_list[idx]['name'])
        print('Selected groups: {}'.format(str(input_groups)))
        return input_groups

    def get_department_user_selection(self):
        for idx, department in enumerate(self.departments):
            print('{}: {}'.format(idx, department['name']))
        dept_idx = int(input('Choose department by index:'))
        dept_name = self.departments[dept_idx]['name']
        print('Selected dept: {}'.format(dept_name))
        return dept_name

    def bulk_add_test_users(self, bulk_users_file_path='tests/resources/17k_users.json'):
        with open(bulk_users_file_path, 'r') as users_f:
            data = json.load(users_f)
            for user in data:
                self.add_test_user(user_to_copy=user)

    @sleep_and_retry
    @limits(calls=10, period=SECONDS_IN_HOUR)
    def remove_users(self, users_id_list):
        users_blk_del_endpoint = 'users/bulkDelete'
        endpoint_url = '/'.join([API_URL, users_blk_del_endpoint])
        for chunk in chunks_of_len(users_id_list):
            blk_del_result = self._session.post(url=endpoint_url,
                                                json={
                                                    'ids': chunk
                                                },
                                                headers=HEADERS)
            print('BULK DELETE USERS RESULT: {}'.format(blk_del_result.status_code))
        time.sleep(61)


if __name__ == '__main__':
    fire.Fire(component=UserManager)
