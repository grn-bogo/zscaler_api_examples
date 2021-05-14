import datetime
import fire
import json
import os
from ratelimit import limits, sleep_and_retry
import re
import requests
import sys
import time
from urllib.parse import quote

HEADERS = {
    'content-type': "application/json",
    # 'cache-control': "no-cache"
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


class TestUserUpload:

    def __init__(self, users_to_upload):
        self.users_to_upload = users_to_upload
        self.next_user_idx = 0

    def get_next(self):
        user_data = self.users_to_upload[self.next_user_idx]
        self.next_user_idx = self.next_user_idx + 1
        return user_data


class DepartmentInterationStatus:
    def __init__(self, departments_list):
        self.departments_list = departments_list
        self.current_department_page = 0
        self.current_department = departments_list[0]


class APIManager:
    SECONDS_IN_HOUR = 60 * 60
    THREE_MINUTES = 3 * 60

    LOCATIONS_ENDPOINT = 'locations'
    LOCATIONS_ENDPOINT_URL = '/'.join([API_URL, LOCATIONS_ENDPOINT])
    LOCATION_ENDPOINT_URL = '/'.join([API_URL, LOCATIONS_ENDPOINT, '{}'])

    DEPARTMENTS_ENDPOINT = 'departments'
    DEPARTMENTS_ENDPOINT_URL = '/'.join([API_URL, DEPARTMENTS_ENDPOINT])
    GROUPS_ENDPOINT = 'groups'
    GROUPS_ENDPOINT_URL = '/'.join([API_URL, GROUPS_ENDPOINT])
    USERS_ENDPOINT = 'users'
    USERS_ENDPOINT_URL = '/'.join([API_URL, USERS_ENDPOINT])
    USER_PUT_ENDPOINT = '/'.join([API_URL, USERS_ENDPOINT, '{}'])

    DEPT_GROUP_PROGRESS_FILE = 'add_dept_group_progress'

    UNAUTH_DEPT_NAME = 'Unauthenticated Transactions'
    ADMIN_DEPT_NAME = 'Service Admin'

    def __init__(self, u, p, k):
        self._session = None
        self._locations_list = None
        self._departments_list = None
        self._departments_dict = None
        self._groups_dict = None
        self._groups_list = None
        self._page_size = 500
        self._login_data = LoginData(usr=u, pwd=p, api_key=k)
        self._test_users_to_upload = None

    def __del__(self):
        self._session.close()

    @staticmethod
    def remove_scim_dept_data(department_name):
        return re.sub('[{}]', '', department_name)

    # move this to class aggregating managers
    def start_auth_session(self):
        self._session = requests.session()
        auth_result = self._session.post(url=AUTH_URL,
                                         headers=HEADERS,
                                         data=self._login_data.to_json())
        print('AUTH RESULT code {0}'.format(auth_result.status_code))
        if auth_result.status_code != 200:
            print("Authentication failed, exiting!")
            sys.exit(-1)

    @sleep_and_retry
    @limits(calls=1, period=1)
    def get_departments(self):
        get_departments_results = self._session.get(url=self.DEPARTMENTS_ENDPOINT_URL,
                                                    headers=HEADERS)
        self._departments_list = json.loads(get_departments_results.content.decode('utf-8'))
        self._departments_dict = {d['name']: d for d in self._departments_list}

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
        if self._departments_list is None:
            self.get_departments()
        return self._departments_list

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
                    self.add_user_to_group(user_obj=user, group_to_add_name=group_to_add_name)
                except Exception as exception:
                    print('EXCEPTION ON PUT USER {} UPDATE ATTEMPT'.format(exception))
                    continue
            page_number += 1

    def save_page_progress(self, department_name, page):
        progress = {'department': department_name, 'page': page}
        with open(APIManager.DEPT_GROUP_PROGRESS_FILE, 'w') as progress_file:
            json.dump(progress, progress_file)

    def load_page_progress(self):
        if os.path.exists(APIManager.DEPT_GROUP_PROGRESS_FILE) and os.path.isfile(
                APIManager.DEPT_GROUP_PROGRESS_FILE):
            with open(APIManager.DEPT_GROUP_PROGRESS_FILE, 'r') as progress_file:
                progress_data = json.load(progress_file)
                return progress_data['department'], progress_data['page']
        else:
            return None, 1

    def groups_for_dept_exist(self):
        self.get_departments()
        self.get_groups()
        no_scim_chars_depts = map(APIManager.remove_scim_dept_data, self._departments_dict.keys())
        no_scim_chars_groups = map(APIManager.remove_scim_dept_data, self._groups_dict.keys())
        departments_names = set(no_scim_chars_depts)
        group_names = set(no_scim_chars_groups)
        # default depratment Service Admin needs to be excluded from this check
        # departments_names.remove('Service Admin')
        if APIManager.UNAUTH_DEPT_NAME in departments_names:
            departments_names.remove(APIManager.UNAUTH_DEPT_NAME)
        if APIManager.UNAUTH_DEPT_NAME in group_names:
            group_names.remove(APIManager.UNAUTH_DEPT_NAME)
        print('GROUP NAMES')
        print(group_names)
        print('DEPARTMENT NAMES')
        print(departments_names)
        diff = departments_names.difference(group_names)
        print('DIFF')
        print(diff)
        if len(diff):
            print('THE FOLLOWING GROUPS NEED TO BE ADDED TO RUN THE SCRIPT:')
            for group in diff:
                print(group)
            print('EXITING')
            sys.exit(-1)

    def add_user_dept_group(self, page_size=None):
        self.start_auth_session()
        self.groups_for_dept_exist()
        if page_size is not None:
            self._page_size = page_size

        dept_name, last_page = self.load_page_progress()
        start_dept_idx = 0
        if dept_name is not None:
            start_dept_idx = self._departments_list.index(self._departments_dict[dept_name])

        start_page = 1
        if last_page != 1:
            start_page = last_page

        for department in self._departments_list[start_dept_idx:]:
            current_dept_name = department['name']
            if current_dept_name == APIManager.UNAUTH_DEPT_NAME or current_dept_name == APIManager.ADMIN_DEPT_NAME:
                continue

            print('STARING DEPARTMENT GROUP INSERT FOR DEPARTMENT {} AT PAGE {}'.format(current_dept_name, start_page))

            clean_dept_name = APIManager.remove_scim_dept_data(current_dept_name)
            if current_dept_name in self._groups_dict:
                department_group = self._groups_dict[current_dept_name]
            else:
                department_group = self._groups_dict[clean_dept_name]

            self.add_department_group(start_page=start_page,
                                      group_to_add=department_group,
                                      input_department=current_dept_name)
            # after first continued department start with page 0
            start_page = 1

    def remove_non_dept_four_char_groups(self, user, department):
        if len(department) == 4 and user['groups'] is not None:
            modified = filter(lambda group: group['name'] == department or len(group['name']) != 4, user['groups'])
            user['groups'] = list(modified)
            print('REMOVED DEPT GROUPS, REMAINING GROUPS ARE {}'.format(user['groups']))
            return True
        return False

    def add_department_group(self, start_page, group_to_add, input_department):
        page_number = start_page
        while True:
            group_to_add_name = group_to_add['name']
            users_data = self.get_users_page_to_modify(input_department=input_department,
                                                       page_number=page_number)
            if len(users_data) == 0:
                break
            for user in users_data:
                try:
                    groups_removed = self.remove_non_dept_four_char_groups(user=user, department=input_department)
                    groups_added = self.add_user_to_group(user_obj=user, group_to_add_name=group_to_add_name)
                    if groups_removed or groups_added:
                        update_result = self.update_user_data(user_obj=user)
                        print('USER PUT UPDATE RESULT: {}'.format(update_result.status_code))

                except Exception as exception:
                    print('EXCEPTION ON PUT USER {} UPDATE ATTEMPT'.format(exception))
                    continue
            page_number += 1
            self.save_page_progress(input_department, page_number)

    def get_and_modify_user_name_from_api(self, start, end):
        page_number = start
        while True:
            if page_number > end:
                break
            # five 500 long user pages per group -> 2.5k users per group
            users_data = self.get_users_page_to_modify(page_number=page_number)
            if len(users_data) == 0:
                break
            for user in users_data:
                try:
                    self.update_user_name(user_obj=user)
                except Exception as exception:
                    print('EXCEPTION ON PUT USER {} UPDATE ATTEMPT'.format(exception))
                    continue
            page_number += 1

    @sleep_and_retry
    @limits(calls=50, period=THREE_MINUTES)
    def update_user_data(self, user_obj):
        return self._session.put(url=self.USER_PUT_ENDPOINT.format(user_obj['id']),
                                 headers=HEADERS,
                                 json=user_obj)

    def add_user_to_group(self, user_obj, group_to_add_name):
        group_to_add = self.groups[group_to_add_name]
        if 'groups' not in user_obj or user_obj['groups'] is None:
            user_obj['groups'] = []
        if group_to_add not in user_obj['groups']:
            user_obj['groups'].append(group_to_add)
            print('UPDATING USER {} WITH GROUP {}'.format(user_obj['email'], group_to_add_name))
            return True
        else:
            print('USER {} ALREADY IN GROUP: {}'.format(user_obj['name'], str(group_to_add)))
            return False

    @sleep_and_retry
    @limits(calls=50, period=THREE_MINUTES)
    def update_user_name(self, user_obj):
        if '@' in user_obj['name']:
            user_obj['name'] = user_obj['name'].split('@')[0]
            put_user_result = self._session.put(url=self.USER_PUT_ENDPOINT.format(user_obj['id']),
                                                headers=HEADERS,
                                                json=user_obj)
            print('USER PUT UPDATE RESULT: {}'.format(put_user_result.status_code))
        else:
            print('USER NAME {} NOT UPDATED'.format(user_obj['name']))

    @sleep_and_retry
    @limits(calls=1, period=6)
    def get_users_page_to_modify(self, input_department=None, page_number=1):
        pagination = 'page={page_no}&pageSize={page_size}'.format(page_no=page_number, page_size=self._page_size)
        if input_department is not None:
            paginated_url = '/'.join(
                [API_URL, self.USERS_ENDPOINT, '?dept=' + quote(input_department) + '&' + pagination])
        else:
            paginated_url = '/'.join([API_URL, self.USERS_ENDPOINT + '?' + pagination])
        get_users_result = self._session.get(url=paginated_url, headers=HEADERS)
        users = json.loads(get_users_result.content.decode('utf-8'))
        return users

    def add_test_user(self):
        user_to_upload = self._test_users_to_upload.get_next()
        user_name = user_to_upload['login_name'].split('@')[0]
        new_user = {
            'name': 'test_user_{}'.format(user_name),
            'email': '{}@bgriner.zscalerthree.net'.format('test___' + user_name),
            # 'department': {'id': 21826133, 'name': 'test_dep_1'},
            'groups': [{'id': 23527799, 'name': 'group_mod_test_9'}],
            # 'department': {'id': 23900665, 'name': 'test_dep_3'},
            # 'department': {'id': 23900667, 'name': 'test_dep_4'},
            'department': {'id': 23900668, 'name': 'test_dep_5'},
            'comments': 'asdas',
            'adminUser': False,
            'password': '1DPUA2UDPA3*'
        }
        post_user_result = self._session.post(url=self.USERS_ENDPOINT_URL,
                                              headers=HEADERS,
                                              json=new_user)
        print('TEST USER POST RESULT: {}'.format(post_user_result.status_code))

    def group_to_dept(self, start=1, end=10000, psize=None, file_path=None):
        if psize is not None:
            self._page_size = psize
        self.start_auth_session()
        dept_name = self.get_department_user_selection()
        input_groups = self.get_groups_user_selection()
        if file_path is None:
            self.get_and_modify_users_from_api(input_department=dept_name,
                                               groups=input_groups,
                                               start=start,
                                               end=end)

    def remove_email_from_user_name(self, start=1, end=10000, psize=None, file_path=None):
        if psize is not None:
            self._page_size = psize
        self.start_auth_session()
        self.get_and_modify_user_name_from_api(start=start, end=end)

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
        self.start_auth_session()
        self.load_test_users_to_post(bulk_users_file_path)
        from twisted.internet.task import LoopingCall
        from twisted.internet import reactor
        lc = LoopingCall(self.add_test_user)
        lc.start(3.5)
        reactor.run()

    def load_test_users_to_post(self, bulk_users_file_path):
        with open(bulk_users_file_path, 'r') as users_f:
            self._test_users_to_upload = TestUserUpload(users_to_upload=json.load(users_f))

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

    def clone_sublocations(self, source_loc, traget_loc):
        self.start_auth_session()

    def check_source_and_target_loc(self, source_loc, target_loc):
        pass

    def get_locations_list(self):
        try:
            self._locations_list = self._session.get(url=self.LOCATIONS_ENDPOINT_URL, headers=HEADERS)
        except Exception as exception:
            print('EXCEPTION AT GETTING LOCATIONS: {}'.format(exception))
            sys.exit(-1)


if __name__ == '__main__':
    fire.Fire(component=APIManager)
