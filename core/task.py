from __future__ import absolute_import, unicode_literals
import logging
import functools
import threading
import ast
import time
from django.http import HttpResponse
from libs import send_email, util
from core.api.serachsql import replace_limit
from libs import call_inception,con_database, file_help
from .models import (
    DatabaseList,
    Account,
    globalpermissions,
    SqlOrder,
    SqlRecord,
    grained,
    querypermissions
)

import json

CUSTOM_ERROR = logging.getLogger('Yearning.core.views')
BLACKLIST = ['update', 'insert', 'alter', 'into', 'for', 'drop']

def set_auth_group(user):
    perm = {
        'ddl': '0',
        'ddlcon': [],
        'dml': '0',
        'dmlcon': [],
        'dql': '0',
        'dqlcon': [],
        'user': '0',
        'base': '0',
        'person': [],
        'query': '0',
        'querycon': []
    }
    group = Account.objects.filter(username=user).first()
    group_list = str(group.auth_group).split(',')
    for group_name in group_list:
        auth = grained.objects.filter(username=group_name).first()
        if auth is not None:
            for k, v in perm.items():
                if isinstance(v, list):
                    v = list(set(v) | set(auth.permissions[k]))
                elif v == '0':
                    v = auth.permissions[k]
                perm[k] = v
    return perm


def grained_permissions(func):
    '''

    :argument 装饰器函数,校验细化权限。非法请求直接返回401交由前端判断状态码

    '''

    @functools.wraps(func)
    def wrapper(self, request, args=None):
        if request.method == "PUT" and args != 'connection':
            return func(self, request, args)
        else:
            if request.method == "GET":
                permissions_type = request.GET.get('permissions_type')
            else:
                permissions_type = request.data['permissions_type']
            if permissions_type == 'own_space' or permissions_type == 'query':
                return func(self, request, args)
            else:
                group = set_auth_group(request.user)
                if group is not None and group[permissions_type] == '1':
                    return func(self, request, args)
                else:
                    return HttpResponse(status=401)

    return wrapper


def ThinkTooMuch(func):
    def wrapper(self, request, args=None):
        if request.method == "DELETE":
            user = args
        elif request.method == "GET":
            user = request.GET.get('username')
        else:
            user = request.data['username']
        if user != str(request.user):
            if request.user.is_staff is not True:
                return HttpResponse('请不要想太多!')
        return func(self, request, args)

    return wrapper


def isAdmin(func):
    def wrapper(self, request, args=None):
        if request.user.is_staff != 1:
            if request.method == "PUT":
                if args == 'group_list':
                    return func(self, request, args)
            elif request.method == "GET":
                if args == 'group_name':
                    return func(self, request, args)
            return HttpResponse('请不要想太多!')
        return func(self, request, args)

    return wrapper


class order_push_message(object):
    '''

    :argument 同意执行工单调用该方法异步处理数据

    '''

    def __init__(self, addr_ip, id, from_user, to_user):
        super().__init__()
        self.id = id
        self.addr_ip = addr_ip
        self.order = SqlOrder.objects.filter(id=id).first()
        self.from_user = from_user
        self.to_user = to_user
        self.title = f'工单:{self.order.work_id}审核通过通知'

    def run(self):
        self.execute()
        self.agreed()


    def execute(self):

        '''

        :argument 将获得的sql语句提交给inception执行并将返回结果写入SqlRecord表,最后更改该工单SqlOrder表中的status

        :param
                self.order
                self.id

        :return: none

        '''
        if self.order.type != 2:
            try:
                detail = DatabaseList.objects.filter(id=self.order.bundle_id).first()

                with call_inception.Inception(
                        LoginDic={
                            'host': detail.ip,
                            'user': detail.username,
                            'password': detail.password,
                            'db': self.order.basename,
                            'port': detail.port
                        }
                ) as f:
                    res = f.Execute(sql=self.order.sql, backup=self.order.backup)
                    for i in res:
                        if i['errlevel'] != 0:
                            SqlOrder.objects.filter(work_id=self.order.work_id).update(status=4)
                        SqlRecord.objects.get_or_create(
                            state=i['stagestatus'],
                            sql=i['sql'],
                            error=i['errormessage'],
                            workid=self.order.work_id,
                            affectrow=i['affected_rows'],
                            sequence=i['sequence'],
                            execute_time=i['execute_time'],
                            SQLSHA1=i['SQLSHA1'],
                            backup_dbname=i['backup_dbname']
                        )
            except Exception as e:
                CUSTOM_ERROR.error(f'{e.__class__.__name__}: {e}')
            finally:
                status = SqlOrder.objects.filter(work_id=self.order.work_id).first()
                if status.status != 4:
                    SqlOrder.objects.filter(id=self.id).update(status=1)
        else:
            #  dql 操作
            un_init = util.init_conf()
            limit = ast.literal_eval(un_init['other'])
            sql = self.order.sql
            check = str(self.order.sql).lower().strip().split(';\n')
            raw_sql = str(self.order.sql).strip().split(';\n')[-1]
            un_init = util.init_conf()
            custom_com = ast.literal_eval(un_init['other'])
            critical = len(custom_com['sensitive_list'])
            # 操作实例
            detail = DatabaseList.objects.filter(id=self.order.bundle_id).first()
            with con_database.SQLgo(
                        ip=detail.ip,
                        password=detail.password,
                        user=detail.username,
                        port=detail.port,
                        db=self.order.basename
            ) as f:
                try:
                    if check[-1].startswith('show'):
                        query_sql = raw_sql
                    else:
                        if limit.get('limit').strip() == '':
                            CUSTOM_ERROR.error('未设置全局最大limit值，系统自动设置为1000')
                            query_sql = replace_limit(raw_sql, 1000)
                        else:
                            query_sql = replace_limit(
                                raw_sql, limit.get('limit'))
                    data_set = f.search(sql=query_sql)    
                except Exception as e:
                    CUSTOM_ERROR.error(f'{e.__class__.__name__}: {e}')
                
                else:           
                    if self.order.sensitive:
                            as_list = sql_as_ex(
                                sql, custom_com['sensitive_list'])
                            if data_set['data']:
                                fe = []
                                for k, v in data_set['data'][0].items():
                                    if isinstance(v, bytes):
                                        fe.append(k)
                                for l in data_set['data']:
                                    if len(fe) != 0:
                                        for i in fe:
                                            l[i] = 'blob字段为不可呈现类型'
                                    for s in as_list:
                                        if l.get(s):
                                            if s == "email":
                                                pattern = re.compile(r"(.*)@(.*)")
                                                res = re.findall(pattern, l[s])
                                                if len(res) != 0:
                                                    l[s] = res[0][0] + "*****"
                                            elif s == "phone":
                                                pattern = re.compile(r"(.{3})(.*)(.{4})")
                                                res = re.findall(pattern, l[s])
                                                if len(res) != 0:
                                                    l[s] = res[0][0] + "*****"  + res[0][-1]   
                                            elif s == "idno":
                                                pattern = re.compile(r"(.*)(.{4})$")
                                                res = re.findall(pattern, l[s])
                                                if len(res) != 0:
                                                    l[s] = res[0][0] + "*****"                                                                                         
                                            else:
                                                l[s] =  l[s][:3] + "****" + l[s][-3:]
                                        else: continue
                    else:
                        if data_set['data']:
                            fe = []
                            for k, v in data_set['data'][0].items():
                                if isinstance(v, bytes):
                                    fe.append(k)
                            if len(fe) != 0:
                                for l in data_set['data']:
                                    for i in fe:
                                        l[i] = 'blob字段为不可呈现类型' 
                    
                    if len(data_set["data"]) > 200:
                        from settingConf.settings import MEDIA_ROOT
                        filename, status = file_help.save_file(data_set, MEDIA_ROOT)
                        if status:
                            querypermissions.objects.create(
                                work_id=self.order.work_id,
                                username=self.order.username,
                                statements=query_sql,
                                filename=filename,
                                answer={"data": [],"title": [],"len":""}
                            )
                        else:
                            CUSTOM_ERROR.error("***file save fail***",filename)
                    else:
                        querypermissions.objects.create(
                            work_id=self.order.work_id,
                            username=self.order.username,
                            statements=query_sql,
                            answer=json.dumps(data_set)
                        )
                    SqlOrder.objects.filter(work_id=self.order.work_id).update(status=1)          


    def agreed(self):

        '''

        :argument 将执行的结果通过站内信,email,dingding 发送

        :param   self.from_user
                 self.to_user
                 self.title
                 self.order
                 self.addr_ip

        :return: none

        '''
        t = threading.Thread(target=order_push_message.con_close, args=(self,))
        t.start()
        t.join()

    def con_close(self):

        content = DatabaseList.objects.filter(id=self.order.bundle_id).first()
        mail = Account.objects.filter(username=self.to_user).first()
        tag = globalpermissions.objects.filter(authorization='global').first()

        if tag.message['ding']:
            try:
                util.dingding(
                    content='# <font face=\"微软雅黑\">工单执行通知</font> \n #  \n <br>  \n  **工单编号:**  %s \n  \n  **发起人员:**  <font color=\"#000080\">%s</font><br /> \n \n  **审核人员:**  <font color=\"#000080\">%s</font><br /> \n \n **平台地址:**  http://%s \n  \n **工单备注:**  %s \n \n **执行状态:**  <font color=\"#38C759\">已执行</font><br /> \n \n **备注:**  %s \n '
                            % (
                                self.order.work_id, self.order.username, self.from_user, self.addr_ip, self.order.text,
                                content.after),
                    url=ding_url())
            except Exception as e:
                CUSTOM_ERROR.error(f'{e.__class__.__name__}--钉钉推送失败: {e}')

        if tag.message['mail']:
            try:
                if mail.email:
                    mess_info = {
                        'workid': self.order.work_id,
                        'to_user': self.order.username,
                        'addr': self.addr_ip,
                        'text': self.order.text,
                        'note': content.after}
                    put_mess = send_email.send_email(to_addr=mail.email)
                    put_mess.send_mail(mail_data=mess_info, type=0)
            except Exception as e:
                CUSTOM_ERROR.error(f'{e.__class__.__name__}--邮箱推送失败: {e}')


class rejected_push_messages(object):
    '''

    :argument 驳回工单调用该方法异步处理数据

    '''

    def __init__(self, _tmpData, to_user, addr_ip, text, from_user):
        super().__init__()
        self.to_user = to_user
        self._tmpData = _tmpData
        self.addr_ip = addr_ip
        self.text = text
        self.from_user = from_user

    def execute(self):

        '''

        :argument 更改该工单SqlOrder表中的status

        :param
                self._tmpData
                self.addr_ip
                self.text
                self.to_user

        :return: none

        '''
        mail = Account.objects.filter(username=self.to_user).first()
        tag = globalpermissions.objects.filter(authorization='global').first()
        if tag.message['ding']:
            try:
                util.dingding(
                    '# <font face=\"微软雅黑\">工单驳回通知</font> \n #  \n <br>  \n  **工单编号:**  %s \n  \n  **发起人员:**  <font color=\"#000080\">%s</font><br /> \n \n **审核人员:**  <font color=\"#000080\">%s</font><br /> \n \n **平台地址:**  http://%s \n \n **状态:**  <font color=\"#FF0000\">驳回</font>\n \n **驳回说明:**  %s'
                    % (self._tmpData['work_id'], self.to_user, self.from_user, self.addr_ip, self.text),
                    url=ding_url())
            except Exception as e:
                CUSTOM_ERROR.error(f'{e.__class__.__name__}--钉钉推送失败: {e}')
        if tag.message['mail']:
            try:
                if mail.email:
                    mess_info = {
                        'workid': self._tmpData['work_id'],
                        'to_user': self.to_user,
                        'addr': self.addr_ip,
                        'rejected': self.text}
                    put_mess = send_email.send_email(to_addr=mail.email)
                    put_mess.send_mail(mail_data=mess_info, type=1)
            except Exception as e:
                CUSTOM_ERROR.error(f'{e.__class__.__name__}--邮箱推送失败: {e}')


class submit_push_messages(threading.Thread):
    '''

    :argument 提交工单调用该方法异步处理数据

    '''

    def __init__(self, workId, user, addr_ip, text, assigned, id):
        super().__init__()
        self.workId = workId
        self.user = user
        self.addr_ip = addr_ip
        self.text = text
        self.assigned = assigned
        self.id = id

    def run(self):
        self.submit()

    def submit(self):
        '''

        :argument 更改该工单SqlOrder表中的status

        :param
                self.workId
                self.user
                self.addr_ip
                self.text
                self.assigned
                self.id
        :return: none

        '''
        content = DatabaseList.objects.filter(id=self.id).first()
        mail = Account.objects.filter(username=self.assigned).first()
        tag = globalpermissions.objects.filter(authorization='global').first()
        if tag.message['ding']:
            try:
                util.dingding(
                    '# <font face=\"微软雅黑\">工单提交通知</font> #  \n <br>  \n  **工单编号:**  %s \n  \n  **提交人员:**  <font color=\"#000080\">%s</font><br /> \n \n **审核人员:**  <font color=\"#000080\">%s</font><br /> \n \n**平台地址:**  http://%s \n  \n **工单说明:**  %s \n \n **状态:**  <font color=\"#FF9900\">已提交</font><br /> \n \n **备注:**  %s \n '
                    % (self.workId, self.user, self.assigned, self.addr_ip, self.text, content.before),
                    url=ding_url())
            except Exception as e:
                CUSTOM_ERROR.error(f'{e.__class__.__name__}--钉钉推送失败: {e}')
        if tag.message['mail']:
            if mail.email:
                mess_info = {
                    'workid': self.workId,
                    'to_user': self.user,
                    'addr': self.addr_ip,
                    'text': self.text,
                    'note': content.before}
                try:
                    put_mess = send_email.send_email(to_addr=mail.email)
                    put_mess.send_mail(mail_data=mess_info, type=99)
                except Exception as e:
                    CUSTOM_ERROR.error(f'{e.__class__.__name__}--邮箱推送失败: {e}')


def ding_url():
    un_init = util.init_conf()
    webhook = ast.literal_eval(un_init['message'])
    return webhook['webhook']


def sql_parse(sql):
    for i in sql.split():
        for c in BLACKLIST:
            if i == c:
                return True

def sql_as_ex(sql, sensitive_list):
    count = 0
    sql = sql.split(',')
    complete = []
    for comma in sql:
        _a = comma.split(' ')
        for _i in _a:
            if _i is not '':
                complete.append(_i)
    for gen in complete:
        if gen == 'as':
            count += 1
    if count != 0:
        as_list = []
        for i in range(len(complete)):
            if complete[i] == 'as':
                for s in sensitive_list:
                    if complete[i - 1] == s:
                        as_list.append(complete[i + 1].rstrip(','))

        if as_list is not None:
            for sen_i in as_list:
                sensitive_list.append(sen_i)
        return sensitive_list
    else:
        return sensitive_list