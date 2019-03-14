##  安装

环境  python3.6  django  mysql inception
step1: 
     `pip install -r requirements.txt` 

由于pymysql这个库连接inception的时候会不兼容智能从 源码当中进行修改

     ```shell
1、找到pymysql的源码路径 修改connections.py文件

vim connections.py

def _request_authentication(self):
        # https://dev.mysql.com/doc/internals/en/connection-phase-packets.html#packet-Protocol::HandshakeResponse
        if int(self.server_version.split('.', 1)[0]) >= 5:
            self.client_flag |= CLIENT.MULTI_RESULTS
修改为
def _request_authentication(self):
        # https://dev.mysql.com/doc/internals/en/connection-phase-packets.html#packet-Protocol::HandshakeResponse
        try:
            if int(self.server_version.split('.', 1)[0]) >= 5:
                self.client_flag |= CLIENT.MULTI_RESULTS
        except:
            if self.server_version.split('.', 1)[0] == 'Inception2':
                self.client_flag |= CLIENT.MULTI_RESULTS
                

2、 查找 pymysql 源码修改 cursors.py文件

vim cursors.py

将这个代码
if self._result and (self._result.has_next or not self._result.warning_count):
    return

改成 
if self._result:
	return

     ```



step2: 
    安装inception 并且启动inception  

​    编辑 /etc/inc.conf    

```shell

[inception]
general_log=1
general_log_file=/var/log/Inception/inception.log
port=6669

socket=/tmp/inc.socket
character-set-client-handshake=0
character-set-server=utf8
inception_support_charset=utf8mb4
inception_enable_nullable=0
inception_check_primary_key=1
inception_check_column_comment=1
inception_check_table_comment=1
inception_enable_blob_type=1
inception_check_column_default_value=1
inception_support_charset=utf8
inception_osc_on=OFF
inception_check_column_default_value=OFF
inception_check_column_comment=OFF
inception_check_table_comment=OFF
inception_enable_identifer_keyword=ON
inception_remote_backup_host = 127.0.0.1 # 此处为备份库mysql地址
inception_remote_backup_port = 3306       # 此处为备份库mysql端口
inception_remote_system_user = root       # 此处为备份库mysql用户
inception_remote_system_password = 127521yzz  # 此处为备份库mysql密码
inception_enable_select_star=0
inception_check_dml_where=0
inception_enable_autoincrement_unsigned=0
```

```shell
 安装Inception  将install/inception.tar 解压后得到 Inception可执行文件
 
 cp Inception /usr/bin  
 
 启动 Inception
 
 Inception --defaults-file=/etc/inc.conf
```

step3 修改数据库相关信息

```shell
cp deploy.conf.template deploy.conf

修改相关数据
[mysql]
db = Yearning
address = your mysql address  
port = your mysql port
username = your mysql user
password = your mysql passwd

[host]
ipaddress = your mysql hostname

```



step4  初始化数据

```shell
python manage.py makemigrations core

python manage.py migrate core

初始化用户
echo "from core.models import Account;Account.objects.create_user(username='admin', password='admin123456', group='admin',auth_group='admin',is_staff=1)" | python manage.py shell

初始化权限
echo "from core.models import grained;grained.objects.get_or_create(username='admin', permissions={'person': [], 'ddl': '1', 'ddlcon': [], 'dml': '1', 'dmlcon': [], 'dic': '1', 'diccon': [], 'dicedit': '0', 'user': '1', 'base': '1', 'dicexport': '0', 'query': '1', 'querycon': [], 'dql': '1', 'dqlcon': []})" | python manage.py shell

初始化全局权限
echo "from core.models import globalpermissions; globalpermissions.objects.get_or_create(authorization='global', inception={'host': '', 'port': '', 'user': '', 'password': '', 'back_host': '', 'back_port': '', 'back_user': '', 'back_password': ''}, ldap={'type': '', 'host': '', 'sc': '', 'domain': '', 'user': '', 'password': ''}, message={'webhook': '', 'smtp_host': '', 'smtp_port': '', 'user': '', 'password': '', 'to_user': '', 'mail': False, 'ding': False}, other={'limit': '', 'con_room': [], 'foce': '', 'multi': False, 'query': False, 'sensitive_list': [], 'sensitive': '', 'exclued_db_list': [], 'email_suffix_list': [], 'exclued_db': '', 'email_suffix': '})" | python manage.py shell  
```



step 5 启动

 ```shell
python manage.py runserver 0.0.0.0:8000
 ```



