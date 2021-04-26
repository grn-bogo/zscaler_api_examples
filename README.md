## Requirements

- Python 3.8 or later
- modules from requirements.txt (pip install -r requirements.txt)

## Grouping users from a selected department

### End result

Users from a selected department will be assigned to groups of similar size which can later by employed to, for instance, gradually 
enable ZTunnel 2.0. The example assumes 17500 users in the department, 500 users per page and group size equal to 5 times page size.

### Example data & example run:

1. Department - needs to be and existing department to which users we want to group are assigned:
 - test_dept_1
 
2. Groups - these need to be added manualy in the admin UI and later selected when prompted by the script:
 - group_1
 - group_2
 - group_3
 - group_4
 - group_5
 - group_6
 - group_7


Run the script using the following command specifing your credentials, 
start at page 1 and end at page 35 (7 groups, each 5 pages, each page holds 500 users)

```bash
python zs_api.py group_to_dept -k <organiztions API key> -u <admin user name> -p <admin user password> -start 1 -end 35
```

You will be prompted to select a department:
```bash
0: Service Admin
1: TestDepartment
2: test_dep_1
3: test_dep_2
Choose department by index:

```
Type department index (2 in our example and press enter)

You will be prompted to select groups:
```bash
0: {'isNonEditable': True, 'id': 959401, 'name': 'Service Admin'}
1: {'id': 11947409, 'name': 'TestGroup', 'comments': 'TestGroup for ZApp new versions and ZTunnel 2.0'}
2: {'id': 21826124, 'name': 'group_1'}
3: {'id': 21826125, 'name': 'group_2'}
4: {'id': 21826126, 'name': 'group_3'}
5: {'id': 21837118, 'name': 'group_4'}
6: {'id': 21837121, 'name': 'group_5'}
7: {'id': 21837124, 'name': 'group_6'}
8: {'id': 21837124, 'name': 'group_7'}
Choose groups by providing comma separted indices:

```

Input comma sperated group indices like this (in our case 2,3,4,5,6,7,8):

```bash
Choose groups by providing comma separted indices:2,3,4,5,6,7,8
```

The run will start and information on progress/errors will be printed in the console.