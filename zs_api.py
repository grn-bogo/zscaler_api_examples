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
    DEPARTMENTS_ENDPOINT = 'departments'
    GROUPS_ENDPOINT = 'groups'
    DEPARTMENTS_ENDPOINT_URL = '/'.join([API_URL, DEPARTMENTS_ENDPOINT])
    GROUPS_ENDPOINT_URL = '/'.join([API_URL, GROUPS_ENDPOINT])

    def __init__(self, authenticated_session):
        self._session = authenticated_session
        self._departments = None
        self._groups = None

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
        self._groups = json.loads(get_groups_results.content.decode('utf-8'))

    @property
    def groups(self):
        if self._groups is None:
            self.get_groups()
        return self._groups

    @property
    def departments(self):
        if self._departments is None:
            self.get_departments()
        return self._departments

    def _validate_groups(self, input_groups):
        existing_group_names = set([group['name'] for group in self.groups])
        if not set(input_groups).issubset(existing_group_names):
            print('ERROR: one or more of input groups is not added in ZIA hosted DB')
            sys.exit()

    def _validate_departments(self, input_department):
        existing_dep_names = set([dep['name'] for dep in self.departments])
        if input_department not in existing_dep_names:
            print('ERROR: input department is not added in ZIA hosted DB')
            sys.exit()


def api_get_endpoints(endpoints):
    try:
        params_list = endpoints.split(',')
        return params_list
    except:
        raise argparse.ArgumentTypeError("use a comma separated endpoints list like: users,locations")


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


def bulk_add_test_users():
    pass


def get_users_to_update_group(session, department, group_list, group_size, start_group):
    departments = get_departments(session=session)
    groups = get_groups(session=session)
    validate_input_groups(groups)

    groups_dict = {group['name']: group for group in groups if group['name'] in group_list}

    page_no = start_group
    while True:
        group_to_add = group_list[page_no - 1]
        group_to_add_obj = groups_dict[group_to_add]
        pagination = '&page={page_no}&pageSize={page_size}'.format(page_no=page_no, page_size=group_size)
        users_endpoint = 'users'
        users_endpoint_url = '/'.join([API_URL, users_endpoint, '?dept=' + department + pagination])
        get_users_result = session.get(url=users_endpoint_url,
                                       headers=HEADERS)
        users = json.loads(get_users_result.content.decode('utf-8'))
        for user in users:
            user_put_endpoint = '/'.join([API_URL, users_endpoint, str(user['id'])])
            if group_to_add_obj not in user['groups']:
                user['groups'].append(group_to_add_obj)
                put_result = session.put(url=user_put_endpoint, headers=HEADERS, json=user)
                print(put_result)

        page_no = page_no + 1
        if page_no > len(group_list):
            break


def validate_input_groups(groups):
    existing_groups = set([group['name'] for group in groups])
    if not set(groups_list).issubset(existing_groups):
        print('ERROR: one or more of input groups is not added in ZIA hosted DB')
        sys.exit()


def get_departments(session):
    departments_endpoint = 'departments'
    departments_endpoint_url = '/'.join([API_URL, departments_endpoint])
    get_user_results = session.get(url=departments_endpoint_url,
                                   headers=HEADERS)
    departments = json.loads(get_user_results.content.decode('utf-8'))
    return departments


def get_groups(session):
    groups_endpoint = 'groups'
    groups_endpoint_url = '/'.join([API_URL, groups_endpoint])
    get_user_results = session.get(url=groups_endpoint_url,
                                   headers=HEADERS)
    groups = json.loads(get_user_results.content.decode('utf-8'))
    return groups


def remove_users(users_id_list):
    users_blk_del_endpoint = 'users/bulkDelete'
    endpoint_url = '/'.join([API_URL, users_blk_del_endpoint])
    for chunk in chunks_of_len(users_id_list):
        blk_del_result = session_requests.post(url=endpoint_url,
                                               json={
                                                   'ids': chunk
                                               },
                                               headers=HEADERS)
        # print('BULK DELETE RESULT: {}'.format(blk_del_result.status_code))
        time.sleep(USR_BLK_COOLDWON)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-u', '--user',
                        type=str,
                        default=None,
                        help='User name for an Admin account on your zscaler admin portal')
    parser.add_argument('-p', '--password',
                        type=str,
                        default=None,
                        help='Password for the account provided under -u/--user')
    parser.add_argument('-k', '--api-key',
                        type=str,
                        default=None,
                        help='API Key from Administration->API Key Management')

    parser.add_argument('-d',
                        help="Department to update group for",
                        default=None,
                        type=str,
                        action='store',
                        dest="filter_str")

    parser.add_argument('-g',
                        help="Groups to add",
                        default="test_group_1",
                        type=str,
                        action='store',
                        dest="groups_str")

    parser.add_argument('-size',
                        help="Size of each group",
                        default=400,
                        type=int,
                        action='store',
                        dest="group_size")

    parser.add_argument('-start',
                        help="Group to start with",
                        default=1,
                        type=int,
                        action='store',
                        dest="start_group")

    args = parser.parse_args()

    login_data = LoginData(usr=args.user,
                           pwd=args.password,
                           api_key=args.api_key)
    session_requests = requests.session()
    filter_str = args.filter_str
    groups_list = args.groups_str.split(',')

    auth_url = '/'.join([API_URL, AUTH_ENDPOINT])
    auth_result = session_requests.post(url=auth_url,
                                        headers=HEADERS,
                                        data=login_data.to_json())

    print('AUTH RESULT code {0}'.format(auth_result.status_code))
    if auth_result.status_code != 200:
        print("Authentication failed, exiting!")
        sys.exit(-1)

    try:
        get_users_to_update_group(
            session=session_requests,
            department=filter_str,
            group_list=groups_list,
            group_size=args.group_size,
            start_group=args.start_group)
    except Exception as exception:
        print(exception)
