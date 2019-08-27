import json
import requests
import time
import datetime


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


headers = {
    'content-type': "application/json",
    'cache-control': "no-cache"
}

API_URL = 'https://admin.zscalertwo.net/api/v1/'
AUTH_ENDPOINT = 'authenticatedSession'
IMPLEMENTED_GET_ENDPOINTS = ['users', 'departments', 'groups',
                             'security',
                             'urlCategories',
                             'vpnCredentials', 'locations',
                             'networkServices']


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

    parser.add_argument('--g',
                        help="GET endpoints to call, comma separated"
                             "for instance --g users,locations",
                        default=None,
                        type=api_get_endpoints,
                        nargs=1,
                        action='store',
                        dest="get_endpoints", )

    args = parser.parse_args()

    login_data = LoginData(usr=args.user,
                           pwd=args.password,
                           api_key=args.api_key)
    session_requests = requests.session()
    get_endpoints = args.get_endpoints[0]

    # authentication
    result = session_requests.post(url=API_URL + AUTH_ENDPOINT,
                                   headers=headers,
                                   data=login_data.to_json())
    print('AUTH RESULT code {0}'.format(result.status_code))

    ts = formatted_datetime()
    for get_endpoint in get_endpoints:
        if get_endpoint  not in IMPLEMENTED_GET_ENDPOINTS:
            print('ENDPOINT: {0} is not implemented'.format(get_endpoint))
            continue
        try:
            get_result = session_requests.get(url=API_URL + get_endpoint,
                                              headers=headers)
            print('ENDPOINT: {endp}, GET RESULT: {code}'.format(endp=get_endpoint, code=get_result.status_code))
            file_name = '{ep}_{ts}'.format(ep=get_endpoint, ts=ts)
            json_obj = json.loads(get_result.content.decode('utf-8'))
            pretty_str = json.dumps(json_obj, indent=4, sort_keys=True)
            with open(file_name, 'w') as json_dump_file:
                json_dump_file.write(pretty_str)

        except Exception as exception:
            print(exception)
