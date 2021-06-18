import json
import fire
import requests
import sys

from ratelimit import limits, sleep_and_retry


class APIManager:
    ZPA_APU_URL = 'https://config.private.zscaler.com/signin'
    AUTH_DATA = 'client_id={id}&client_secret={secret}'
    HEADERS = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    DEFAULT_PAGE_SIZE = 200

    PAGINATION = '?page={page_no}&pagesize={page_size}&search='
    APP_SEGMENTS_EP = 'https://config.private.zscaler.com/mgmtconfig/v1/admin/customers/{segment_id}/application'

    def __init__(self, ci, ti, s, page_size=None):
        self._session = None
        self._tenant_id = ti
        self._client_id = ci
        self._client_secret = s
        self._page_size = APIManager.DEFAULT_PAGE_SIZE
        if page_size and page_size < APIManager.DEFAULT_PAGE_SIZE:
            self._page_size = page_size

        self._app_segments_list = None
        self._app_segments_endpoint = APIManager.APP_SEGMENTS_EP.format(segment_id=self._tenant_id)

    def authenticated_session(self):
        self._session = requests.session()
        auth_data = APIManager.AUTH_DATA.format(id=self._client_id, secret=self._client_secret)
        auth_result = self._session.post(url=APIManager.ZPA_APU_URL,
                                         headers=APIManager.HEADERS,
                                         data=auth_data)
        auth_rep = json.loads(auth_result.content)
        print(F'AUTH_DATA: {auth_data}')
        if auth_result.status_code == 200:
            APIManager.HEADERS['Authorization'] = F"{auth_rep['token_type']} {auth_rep['access_token']}"
            print(F'AUTHENTICATION SUCCESSFUL, RESPONSE CODE: {auth_result.status_code}')
        else:
            print(F'AUTHENTICATION FAILED. RESPONSE CODE: {auth_result.status_code}')
            sys.exit(-1)

    def port_ranges_str(self, ports_list):
        port_ranges = []
        for idx, port in enumerate(ports_list):
            if idx % 2 == 0:
                port_ranges.append(F'{ports_list[idx]}-{ports_list[idx - 1]}')
        return port_ranges

    def dump_app_segments(self):
        self.authenticated_session()
        self.get_app_segments()
        with open(F'app_domians_dump_{self._tenant_id}.txt', 'w') as dump_file:
            for app_seg in self.app_segments:
                dump_file.write(F"{app_seg['name']} ({app_seg['segmentGroupName']})")
                dump_file.write('\n')
                self.dump_port_ranges(app_seg, 'TCP', dump_file)
                self.dump_port_ranges(app_seg, 'UDP', dump_file)
                for domain in app_seg['domainNames']:
                    dump_file.write(domain)
                    dump_file.write('\n')

    def dump_port_ranges(self, app_seg, proto, dump_file):
        ports_key = None
        if proto == 'UDP':
            ports_key = 'udpPortRanges'
        elif proto == 'TCP':
            ports_key = 'tcpPortRanges'
        if ports_key in app_seg:
            port_ranges = self.port_ranges_str(app_seg[ports_key])
            dump_file.write(F'{proto} PORT RANGES: {",".join(port_ranges)}')
            dump_file.write('\n')

    @property
    def app_segments(self):
        if self._app_segments_list:
            return self._app_segments_list
        else:
            self.get_app_segments()
            return self._app_segments_list

    def get_app_segments(self):
        self._app_segments_list = self.get_paginated_list(endpoint_url=self._app_segments_endpoint)

    @sleep_and_retry
    @limits(calls=1, period=2)
    def get_data_list(self, data_url):
        results = self._session.get(url=data_url, headers=APIManager.HEADERS)
        if results.status_code != 200:
            print(F'ERROR CODE {results.status_code} AT COLLECTING DATA FROM {data_url}')
            sys.exit(-1)
        object_list = json.loads(results.content.decode('utf-8'))
        return object_list

    def get_paginated_list(self, endpoint_url):
        data_list = []
        page_no = 1
        while True:
            pagination = F'?page={page_no}&pageSize={self._page_size}'
            paginated_url = endpoint_url + pagination
            rep_data_obj = self.get_data_list(data_url=paginated_url)
            data_list = data_list + rep_data_obj['list']
            print(F'GOT DATA PAGE {page_no} FROM URL {endpoint_url}')
            page_no = page_no + 1
            if page_no > int(rep_data_obj['totalPages']):
                break
        return data_list


if __name__ == '__main__':
    fire.Fire(component=APIManager)
