#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道工具公共库
提供 ZentaoClient 和 VaultClient 的通用实现
"""

import requests
import json
import re
import os
import sys
import subprocess
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta


def get_workspace_dir() -> str:
    """Resolve a caller-configurable directory for generated artifacts."""
    workspace = os.getenv('ZENTAO_WORKSPACE_DIR') or os.getenv('HERMES_WORKSPACE') or os.getcwd()
    return os.path.abspath(os.path.expanduser(workspace))


def get_artifact_dir(*parts: str) -> str:
    """Return and create a directory below the caller-owned workspace."""
    path = os.path.join(get_workspace_dir(), 'zentao-artifacts', *parts)
    os.makedirs(path, exist_ok=True)
    return path


def find_playwright_python(candidates: Optional[List[str]] = None) -> Optional[str]:
    """Return an executable Python interpreter that can import Playwright."""
    if candidates is None:
        candidates = [os.getenv('ZENTAO_PLAYWRIGHT_PYTHON', ''), sys.executable]

    for python_exec in candidates:
        if not python_exec or not os.path.isfile(python_exec) or not os.access(python_exec, os.X_OK):
            continue
        try:
            probe = subprocess.run(
                [python_exec, '-c', 'import playwright'],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            return python_exec
    return None


class ZentaoError(Exception):
    """禅道操作异常"""
    pass


class ZentaoWriteOutcomeUnknown(ZentaoError):
    """写请求已发出，但客户端无法确认服务端是否保存成功。"""
    pass


class VaultError(Exception):
    """Vault 操作异常"""
    pass


class _ZentaoFormParser(HTMLParser):
    """Best-effort parser for Zentao HTML forms.

    The task edit endpoint is an HTML form flow rather than a stable public API
    in this workspace.  Keep the parser conservative: collect posted fields and
    preserve unknown hidden/default values so callers only override explicitly
    requested fields.
    """

    def __init__(self):
        super().__init__()
        self.fields: Dict[str, Any] = {}
        self.form_action: Optional[str] = None
        self._in_textarea: Optional[str] = None
        self._textarea_chunks: List[str] = []
        self._select_name: Optional[str] = None
        self._select_selected_value: Optional[str] = None
        self._select_first_value: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == 'form' and not self.form_action:
            self.form_action = attrs_dict.get('action')

        if tag == 'input':
            name = attrs_dict.get('name')
            if not name:
                return
            input_type = attrs_dict.get('type', '').lower()
            if input_type in {'button', 'submit', 'reset', 'file', 'image'}:
                return
            if input_type in {'checkbox', 'radio'} and 'checked' not in attrs_dict:
                return
            self._add_field(name, attrs_dict.get('value', ''))

        elif tag == 'textarea':
            name = attrs_dict.get('name')
            if name:
                self._in_textarea = name
                self._textarea_chunks = []

        elif tag == 'select':
            self._select_name = attrs_dict.get('name')
            self._select_selected_value = None
            self._select_first_value = None

        elif tag == 'option' and self._select_name:
            value = attrs_dict.get('value', '')
            if self._select_first_value is None:
                self._select_first_value = value
            if 'selected' in attrs_dict:
                self._select_selected_value = value

    def handle_data(self, data):
        if self._in_textarea:
            self._textarea_chunks.append(data)

    def handle_endtag(self, tag):
        if tag == 'textarea' and self._in_textarea:
            self.fields[self._in_textarea] = unescape(''.join(self._textarea_chunks))
            self._in_textarea = None
            self._textarea_chunks = []

        elif tag == 'select' and self._select_name:
            value = self._select_selected_value
            if value is None:
                value = self._select_first_value or ''
            self.fields[self._select_name] = value
            self._select_name = None
            self._select_selected_value = None
            self._select_first_value = None

    def _add_field(self, name: str, value: str):
        value = unescape(value)
        if name.endswith('[]'):
            existing = self.fields.get(name)
            if existing is None:
                self.fields[name] = [value]
            elif isinstance(existing, list):
                existing.append(value)
            else:
                self.fields[name] = [existing, value]
        else:
            self.fields[name] = value


class VaultClient:
    """
    Vault REST API 客户端
    支持从 Vault 读取凭据
    """

    def __init__(self, addr: Optional[str] = None, token: Optional[str] = None):
        """
        初始化 Vault 客户端
        
        Args:
            addr: Vault 服务地址，默认从环境变量 VAULT_ADDR 读取
            token: Vault 访问令牌，默认从环境变量 VAULT_TOKEN 读取
        """
        self.addr = (addr or os.getenv('VAULT_ADDR', 'http://127.0.0.1:8200')).rstrip('/')
        # token 优先级：显式入参 > VAULT_TOKEN 环境变量 > ~/.vault-token 文件
        # 文件兜底是必要的：由 GUI（Dock/Finder）启动的进程不加载 ~/.zshrc，
        # 环境变量经常拿不到，而 ~/.vault-token 是 Vault CLI 的官方约定位置。
        self.token = token or os.getenv('VAULT_TOKEN', '') or self._read_token_file()

        if not self.token:
            raise VaultError(
                "未设置 Vault Token：请设置 VAULT_TOKEN 环境变量，"
                "或写入 ~/.vault-token 文件（Vault CLI 约定）"
            )
        
        self.headers = {
            'X-Vault-Token': self.token,
            'Content-Type': 'application/json'
        }

    @staticmethod
    def _read_token_file() -> str:
        """回退读取 ~/.vault-token（Vault CLI 约定位置）。

        由 GUI 启动的进程（桌面 App、launchd 任务）不加载 shell rc 文件，
        VAULT_TOKEN 常常取不到；文件兜底可绕开这条环境变量继承链。
        """
        try:
            path = os.path.expanduser('~/.vault-token')
            if os.path.isfile(path):
                with open(path, encoding='utf-8') as f:
                    return f.read().strip()
        except OSError:
            pass
        return ''

    def get_secret(self, path: str) -> Dict[str, Any]:
        """
        从 Vault 获取密钥
        
        Args:
            path: 密钥路径，例如 "v1/secret/data/zentao"
            
        Returns:
            密钥数据字典
            
        Raises:
            VaultError: 获取失败时抛出
        """
        # 确保路径格式正确
        if not path.startswith('v1/'):
            path = f"v1/{path}"
        
        url = f"{self.addr}/{path}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            # KV v2 格式: data.data.metadata
            if 'data' in data and 'data' in data['data']:
                return data['data']['data']
            elif 'data' in data:
                return data['data']
            else:
                return data
                
        except requests.exceptions.RequestException as e:
            # 只输出地址，便于区分 8200/错误主机等环境问题；绝不回显 token 或密码。
            raise VaultError(f"请求 Vault 失败 ({self.addr}): {e}")
        except json.JSONDecodeError as e:
            raise VaultError(f"解析 Vault 响应失败: {e}")

    def get_zentao_credentials(self) -> Tuple[str, str]:
        """
        获取禅道登录凭据
        
        Returns:
            (用户名, 密码) 元组
            
        Raises:
            VaultError: 获取失败或凭据不完整时抛出
        """
        # 尝试多个可能的路径；默认使用周维账号的独立凭据路径。
        paths = [
            'v1/secret/data/zentao/zhouwei',
            'v1/secret/zentao/zhouwei',
            'secret/data/zentao/zhouwei',
            'secret/zentao/zhouwei'
        ]
        
        for path in paths:
            try:
                credentials = self.get_secret(path)
                username = credentials.get('username')
                password = credentials.get('password')
                
                if username and password:
                    return username, password
            except VaultError:
                continue
        
        raise VaultError("无法从 Vault 获取禅道凭据，请检查路径和凭据格式")


class ZentaoClient:
    """
    禅道 API 客户端
    提供登录、创建任务、获取项目列表等功能
    """

    # 支持的禅道服务配置
    SERVICES = {
        'keji': {
            'name': '科技部门',
            'url_env': 'ZENTAO_URL_KEJI',
            'default_url': 'https://typm.tygps.com'
        },
        'tianyi': {
            'name': '田一部门', 
            'url_env': 'ZENTAO_URL_TIANYI',
            'default_url': 'https://tycd.tygps.com'
        }
    }

    def __init__(self, base_url: Optional[str] = None):
        """
        初始化禅道客户端
        
        Args:
            base_url: 禅道服务地址，默认从环境变量读取或使用默认值
        """
        self.base_url = (base_url or self._get_default_url()).rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.username: Optional[str] = None
        self._logged_in = False

    @classmethod
    def _get_default_url(cls) -> str:
        """获取默认禅道 URL"""
        return os.getenv('ZENTAO_URL_DEFAULT', 'https://tycd.tygps.com')

    @classmethod
    def detect_service_from_text(cls, text: str) -> str:
        """
        从文本中检测禅道服务
        
        Args:
            text: 用户输入文本
            
        Returns:
            检测到的禅道服务 URL
        """
        text_lower = text.lower()
        
        # 检测关键词
        if '科技' in text_lower or 'typm' in text_lower:
            return os.getenv(cls.SERVICES['keji']['url_env'], 
                           cls.SERVICES['keji']['default_url'])
        elif '田一' in text_lower or 'tycd' in text_lower:
            return os.getenv(cls.SERVICES['tianyi']['url_env'],
                           cls.SERVICES['tianyi']['default_url'])
        else:
            return cls._get_default_url()

    @property
    def is_logged_in(self) -> bool:
        """检查是否已登录"""
        return self._logged_in

    def login(self, username: str, password: str) -> bool:
        """
        登录禅道
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            登录是否成功
            
        Raises:
            ZentaoError: 登录过程中发生错误
        """
        # 尝试多个可能的登录路径
        paths_to_try = ['/biz/user-login.html', '/zentao/user-login.html', '/user-login.html']
        
        for path in paths_to_try:
            url = f"{self.base_url}{path}"
            
            try:
                # 获取登录页面
                page_resp = self.session.get(url, timeout=10)
                
                if page_resp.status_code != 200:
                    continue
                
                page_text = page_resp.text
                
                # 准备登录数据
                login_data = {
                    'account': username,
                    'password': password,
                    'referer': f'{self.base_url}/biz/'
                }
                
                # 提取 verifyRand（如果存在）
                verify_rand = self._extract_verify_rand(page_text)
                if verify_rand:
                    login_data['verifyRand'] = verify_rand
                
                # 执行登录
                login_resp = self.session.post(url, data=login_data, timeout=10)
                
                if login_resp.status_code == 200:
                    # 检查登录是否成功
                    if self._verify_login_success(login_resp):
                        self.username = username
                        self._logged_in = True
                        return True
                    
            except requests.exceptions.RequestException as e:
                continue
        
        raise ZentaoError(f"登录失败，已尝试所有路径: {self.base_url}")

    def login_with_available_credentials(self, vault_client: Optional[VaultClient] = None) -> bool:
        """仅使用 Vault 凭据登录；禁止读取 ZENTAO_USERNAME/ZENTAO_PASSWORD。"""
        return self.login_from_vault(vault_client)

    def login_from_vault(self, vault_client: Optional[VaultClient] = None) -> bool:
        """
        从 Vault 读取凭据并登录
        
        Args:
            vault_client: Vault 客户端实例，为 None 时自动创建
            
        Returns:
            登录是否成功
        """
        if vault_client is None:
            vault_client = VaultClient()
        
        username, password = vault_client.get_zentao_credentials()
        return self.login(username, password)

    def _extract_verify_rand(self, html_content: str) -> Optional[str]:
        """从页面提取 verifyRand"""
        patterns = [
            r'name=["\']verifyRand["\'][^>]*value=["\']([^"\']+)["\']',
            r'verifyRand["\']?\s*[:=]\s*["\']([^"\']+)["\']'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html_content)
            if match:
                return match.group(1)
        
        return None

    def _extract_form_token(self, html_content: str) -> Optional[str]:
        """从页面提取表单 token"""
        pattern = r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']'
        match = re.search(pattern, html_content)
        return match.group(1) if match else None

    def _extract_error_from_html(self, html_content: str) -> Optional[str]:
        """从 HTML 错误页中提取真实错误信息（禅道 SQL 错误等）。"""
        # 匹配禅道 SQL 错误: ERROR: ...
        sql_match = re.search(r'ERROR:\s*(.*?)(?:&lt;|<)p&gt;', html_content, re.DOTALL)
        if sql_match:
            msg = sql_match.group(1).strip()
            # 清理 HTML 实体
            msg = msg.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
            return msg

        # 匹配禅道通用错误框架: ... on line ... when visiting ...
        when_match = re.search(r'in <strong>(.*?)</strong> on line <strong>(\d+)</strong> when visiting <strong>(.*?)</strong>', html_content)
        if when_match:
            return f"{when_match.group(3)} 出错 ({when_match.group(1)}:{when_match.group(2)})"

        # 匹配 ERROR: 行
        err_match = re.search(r'ERROR:\s*([^<\n]{10,200})', html_content)
        if err_match:
            return err_match.group(1).strip()

        return None

    def _verify_login_success(self, response) -> bool:
        """验证登录是否成功"""
        # 检查响应内容
        if 'task-view' in response.url or 'project-browse' in response.url:
            return True
        
        # 检查是否是 JSON 响应
        try:
            result = response.json()
            if result.get('result') == 'success' or result.get('status') == 'success':
                return True
        except:
            pass
        
        # 检查页面内容
        if '用户登录' in response.text or 'login' in response.text.lower():
            return False
        
        # 如果响应不是登录页面，认为登录成功
        return True

    def get_projects(self) -> List[Dict[str, Any]]:
        """
        获取项目列表
        
        Returns:
            项目列表，每个项目包含 id, name, code, status 等字段
            
        Raises:
            ZentaoError: 获取失败时抛出
        """
        if not self._logged_in:
            raise ZentaoError("未登录，请先调用 login()")
        
        # 尝试多个 API 接口
        apis = [
            '/biz/project-browse.json',
            '/biz/project-all.json',
            '/zentao/project-browse.json',
            '/zentao/project-all.json'
        ]
        
        for api in apis:
            url = f"{self.base_url}{api}"
            
            try:
                response = self.session.get(url, timeout=10)
                
                if response.status_code != 200:
                    continue
                
                result = response.json()
                
                if 'data' in result and isinstance(result['data'], str):
                    # data 是 JSON 字符串
                    data = json.loads(result['data'])
                elif 'data' in result:
                    data = result['data']
                else:
                    data = result
                
                # 尝试多种数据结构
                projects = None
                
                if 'projects' in data:
                    projects = data['projects']
                elif 'projectStats' in data:
                    projects = data['projectStats']
                
                if projects:
                    # 统一格式为列表
                    if isinstance(projects, dict):
                        return [{'id': k, 'name': v} for k, v in projects.items()]
                    elif isinstance(projects, list):
                        return projects
                        
            except (requests.exceptions.RequestException, json.JSONDecodeError):
                continue
        
        raise ZentaoError("无法获取项目列表，已尝试所有 API 接口")

    def get_modules(self, project_id: int) -> List[Dict[str, Any]]:
        """
        获取项目模块列表
        
        Args:
            project_id: 项目 ID
            
        Returns:
            模块列表，每个模块包含 id, name, parent 等字段
            
        Raises:
            ZentaoError: 获取失败时抛出
        """
        if not self._logged_in:
            raise ZentaoError("未登录，请先调用 login()")
        
        return self.get_task_creation_options(project_id)['modules']

    def get_task_creation_options(self, project_id: int) -> Dict[str, Any]:
        """读取创建页中实际可选的模块和负责人，不产生写操作。"""
        url = f"{self.base_url}/biz/task-create-{project_id}.html"
        
        try:
            response = self.session.get(url, timeout=10)
            
            if response.status_code != 200:
                raise ZentaoError(f"无法访问任务创建页面: {response.status_code}")
            
            # 仅解析指定下拉框，避免混入 project 等其他 option。
            modules = []
            select_match = re.search(
                r'<select[^>]*name=["\']module["\'][^>]*>(.*?)</select>',
                response.text,
                re.DOTALL
            )

            if not select_match:
                raise ZentaoError("未找到模块选择器")

            select_html = select_match.group(1)
            module_pattern = r'<option[^>]*value=["\'](\d+)["\'][^>]*>(.*?)</option>'
            matches = re.findall(module_pattern, select_html, re.DOTALL)

            for match in matches:
                module_id, module_name = match
                module_name = re.sub(r'\s+', ' ', module_name).strip()
                if module_id and module_id != '0':
                    modules.append({
                        'id': int(module_id),
                        'name': module_name
                    })

            assignees = []
            assignee_match = re.search(
                r'<select[^>]*name=["\']assignedTo\[\]["\'][^>]*>(.*?)</select>',
                response.text,
                re.DOTALL,
            )
            if assignee_match:
                assignee_pattern = r'<option[^>]*value=["\']([^"\']*)["\'][^>]*>(.*?)</option>'
                for account, label in re.findall(assignee_pattern, assignee_match.group(1), re.DOTALL):
                    if account:
                        assignees.append({
                            'account': account,
                            'name': re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', '', label))).strip(),
                        })

            return {'modules': modules, 'assignees': assignees}
            
        except requests.exceptions.RequestException as e:
            raise ZentaoError(f"获取模块列表失败: {e}")

    def get_project_info(self, project_id: int) -> Dict[str, Any]:
        """读取项目状态，供创建前预检使用。"""
        if not self._logged_in:
            raise ZentaoError("未登录，请先调用 login()")

        try:
            response = self.session.get(f"{self.base_url}/biz/project-view-{project_id}.json", timeout=10)
            response.raise_for_status()
            result = response.json()
            data = result.get('data', result)
            if isinstance(data, str):
                data = json.loads(data)
            project = data.get('project', data) if isinstance(data, dict) else {}
            if not isinstance(project, dict) or not project:
                raise ZentaoError("项目详情响应中没有项目数据")
            return project
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            raise ZentaoError(f"获取项目详情失败: {e}")

    def create_task(self, project_id: int, name: str, **kwargs) -> Dict[str, Any]:
        """
        创建任务
        
        Args:
            project_id: 项目 ID
            name: 任务名称
            **kwargs: 其他可选参数
                - module: 模块 ID
                - assigned_to: 指派人
                - task_type: 任务类型 (design, devel, test, study, discuss, ui, affair)
                - estimate: 预计工时
                - begin: 开始日期 (YYYY-MM-DD)
                - end: 结束日期 (YYYY-MM-DD)
                - pri: 优先级 (1-4)
                - desc: 任务描述
                
        Returns:
            创建的任务信息，包含 id 等字段
            
        Raises:
            ZentaoError: 创建失败时抛出
        """
        if not self._logged_in:
            raise ZentaoError("未登录，请先调用 login()")
        
        # 获取创建页面
        create_url = f"{self.base_url}/biz/task-create-{project_id}.html"
        stage = 'fetch_form'

        try:
            response = self.session.get(create_url, timeout=10)
            
            if response.status_code != 200:
                raise ZentaoError(f"无法访问任务创建页面: {response.status_code}")
            
            # 提取表单 token
            token = self._extract_form_token(response.text)
            
            # 准备任务数据（仅包含当前禅道版本实际存在的字段）
            now = datetime.now()
            default_begin = (now - timedelta(days=5)).strftime('%Y-%m-%d')
            default_end = (now + timedelta(days=10)).strftime('%Y-%m-%d')
            estimate = kwargs.get('estimate')
            estimate = str(estimate).strip() if estimate not in (None, '') else '10'
            task_data = {
                'module': str(kwargs.get('module', '0')),
                'assignedTo[]': kwargs.get('assigned_to', ''),
                'name': name,
                'pri': str(kwargs.get('pri', '3')),
                'estimate': estimate,
                'left': estimate,
                'estStarted': kwargs.get('begin') or default_begin,
                'deadline': kwargs.get('end') or default_end,
                'desc': kwargs.get('desc', ''),
                'type': kwargs.get('task_type', 'devel'),
                'uid': 'kuid',
                'after': 'toTaskList'
            }

            if token:
                task_data['token'] = token

            # 提交创建请求。进入此阶段后的网络中断无法证明服务端没有保存。
            submit_url = f"{self.base_url}/biz/task-create-{project_id}.json"
            stage = 'submit'
            response = self.session.post(submit_url, data=task_data, timeout=15)
            
            if response.status_code != 200:
                raise ZentaoError(f"创建请求失败: {response.status_code}")
            
            # 解析响应
            try:
                result = response.json()

                if result.get('result') == 'success':
                    task_info = {
                        'success': True,
                        'locate': result.get('locate', ''),
                        'message': result.get('message', '')
                    }

                    locate = result.get('locate', '')
                    task_id_match = re.search(r'task-view-(\d+)', locate)
                    if task_id_match:
                        task_info['id'] = int(task_id_match.group(1))
                    return task_info
                else:
                    error_msg = result.get('message', '未知错误')
                    raise ZentaoError(f"创建任务失败: {error_msg}")

            except json.JSONDecodeError:
                # 响应不是 JSON，可能是 HTML 错误页。必须先识别 alert；
                # 不能仅因 HTML 中出现普通的 “task” 文本就误判创建成功。
                error_detail = self._extract_error_from_html(response.text)
                alert_match = re.search(
                    r"alert\(\s*['\"](.*?)['\"]\s*\)",
                    response.text,
                    re.DOTALL,
                )
                if error_detail:
                    raise ZentaoError(f"创建任务失败: {error_detail}")
                elif alert_match:
                    raise ZentaoError(f"创建任务失败: {alert_match.group(1).strip()}")
                elif 'task-view' in response.url or re.search(r'task-view-\d+', response.text):
                    return {'success': True}
                else:
                    raise ZentaoWriteOutcomeUnknown("无法解析创建响应；必须按项目和精确任务名确认结果")

        except requests.exceptions.RequestException as e:
            if stage == 'submit':
                raise ZentaoWriteOutcomeUnknown(f"创建请求结果未知: {e}")
            raise ZentaoError(f"创建任务请求失败: {e}")

    def get_task_edit_form(self, task_id: int) -> Dict[str, Any]:
        """
        获取任务编辑表单并解析当前字段。

        Args:
            task_id: 任务 ID

        Returns:
            {
                'task_id': int,
                'url': 编辑页 URL,
                'action': 表单 action（可能为空）,
                'fields': 当前表单字段,
                'html': 原始 HTML
            }

        Raises:
            ZentaoError: 未登录、任务不存在或无法解析时抛出
        """
        if not self._logged_in:
            raise ZentaoError("未登录，请先调用 login()")

        urls = [
            f"{self.base_url}/biz/task-edit-{task_id}.html?onlybody=yes",
            f"{self.base_url}/biz/task-edit-{task_id}.html",
            f"{self.base_url}/zentao/task-edit-{task_id}.html?onlybody=yes",
            f"{self.base_url}/zentao/task-edit-{task_id}.html",
        ]

        last_status = None
        for url in urls:
            try:
                response = self.session.get(url, timeout=15)
                last_status = response.status_code
            except requests.exceptions.RequestException:
                continue

            if response.status_code == 404:
                continue
            if response.status_code != 200:
                continue

            html = response.text
            if 'user-login' in response.url or '用户登录' in html:
                raise ZentaoError("登录已失效，无法访问任务编辑页")

            parser = _ZentaoFormParser()
            parser.feed(html)
            fields = parser.fields

            # Zentao often exposes a JavaScript kuid and expects it as uid.
            if 'uid' not in fields:
                kuid = self._extract_kuid(html)
                if kuid:
                    fields['uid'] = kuid

            # A valid edit form should at least include one editable task field.
            if any(key in fields for key in ('name', 'module', 'estimate', 'left', 'deadline')):
                return {
                    'task_id': task_id,
                    'url': url,
                    'action': parser.form_action,
                    'fields': fields,
                    'html': html
                }

        raise ZentaoError(f"无法访问任务编辑页面，最后状态码: {last_status}")

    def get_task_detail(self, task_id: int) -> Dict[str, Any]:
        """
        获取任务当前可编辑信息。

        该方法优先读取编辑表单，因为表单字段最接近提交所需的数据；
        视图页仅作为补充来源。
        """
        edit_form = self.get_task_edit_form(task_id)
        fields = edit_form['fields']
        detail: Dict[str, Any] = {
            'id': task_id,
            'name': fields.get('name', ''),
            'module': fields.get('module', ''),
            'estimate': fields.get('estimate', ''),
            'left': fields.get('left', ''),
            'deadline': fields.get('deadline', ''),
            'project': fields.get('project') or fields.get('execution') or fields.get('projectID') or '',
            'raw_fields': fields,
        }

        # Some Zentao pages do not include project as a normal form field.
        if not detail['project']:
            project_match = re.search(
                r'(?:projectID|project|execution)["\']?\s*[:=]\s*["\']?(\d+)',
                edit_form['html']
            )
            if project_match:
                detail['project'] = project_match.group(1)

        return detail

    def update_task(self, task_id: int, **changes) -> Dict[str, Any]:
        """
        修改任务基础信息。

        支持字段:
            - name: 标题
            - module: 模块 ID
            - estimate: 预计工时
            - left: 剩余工时
            - deadline: 截止日期

        未传入字段会保留编辑表单中的原值。
        """
        allowed_fields = {'name', 'module', 'estimate', 'left', 'deadline', 'estStarted'}
        unknown = set(changes) - allowed_fields
        if unknown:
            raise ZentaoError(f"不支持修改字段: {', '.join(sorted(unknown))}")

        edit_form = self.get_task_edit_form(task_id)
        task_data = dict(edit_form['fields'])

        for key, value in changes.items():
            if value is not None:
                task_data[key] = str(value)

        submit_urls = self._task_edit_submit_urls(task_id, edit_form)
        last_error = None
        for submit_url in submit_urls:
            try:
                response = self.session.post(
                    submit_url,
                    data=task_data,
                    headers={
                        'Referer': edit_form['url'],
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    timeout=15
                )
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                continue

            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}"
                continue

            parsed = self._parse_task_update_response(response, task_id)
            if parsed.get('success'):
                return parsed

            last_error = parsed.get('message') or '服务器未返回成功状态'

        raise ZentaoError(f"修改任务失败: {last_error or '未知错误'}")

    def verify_task_updated(self, task_id: int, expected: Dict[str, Any]) -> Dict[str, Any]:
        """
        重新读取任务编辑表单，验证期望字段是否已更新。

        Returns:
            {'success': bool, 'detail': dict, 'mismatches': dict}
        """
        detail = self.get_task_detail(task_id)
        mismatches = {}
        for key, expected_value in expected.items():
            if expected_value is None:
                continue
            actual_value = detail.get(key)
            if str(actual_value) != str(expected_value):
                mismatches[key] = {
                    'expected': str(expected_value),
                    'actual': '' if actual_value is None else str(actual_value)
                }

        return {
            'success': not mismatches,
            'detail': detail,
            'mismatches': mismatches
        }

    def _task_edit_submit_urls(self, task_id: int, edit_form: Dict[str, Any]) -> List[str]:
        """Build likely task edit submit URLs, preferring the form action."""
        urls: List[str] = []
        action = edit_form.get('action')
        if action:
            action_url = urljoin(edit_form['url'], action)
            urls.append(action_url)
            if action_url.endswith('.html'):
                urls.append(action_url[:-5] + '.json')

        urls.extend([
            f"{self.base_url}/biz/task-edit-{task_id}.json",
            f"{self.base_url}/biz/task-edit-{task_id}.html?onlybody=yes",
            f"{self.base_url}/zentao/task-edit-{task_id}.json",
            f"{self.base_url}/zentao/task-edit-{task_id}.html?onlybody=yes",
        ])

        deduped = []
        for url in urls:
            if url not in deduped:
                deduped.append(url)
        return deduped

    def _extract_kuid(self, html_content: str) -> Optional[str]:
        """从页面脚本中提取 kuid。"""
        patterns = [
            r"kuid\s*=\s*['\"]([^'\"]+)['\"]",
            r"['\"]kuid['\"]\s*[:=]\s*['\"]([^'\"]+)['\"]",
        ]
        for pattern in patterns:
            match = re.search(pattern, html_content)
            if match:
                return match.group(1)
        return None

    def _parse_task_update_response(self, response, task_id: int) -> Dict[str, Any]:
        """解析任务修改响应。"""
        try:
            result = response.json()
            if result.get('result') == 'success' or result.get('status') == 'success':
                return {
                    'success': True,
                    'message': result.get('message', ''),
                    'locate': result.get('locate', ''),
                }
            return {
                'success': False,
                'message': result.get('message', '服务器返回失败状态')
            }
        except json.JSONDecodeError:
            pass

        error_detail = self._extract_error_from_html(response.text)
        if error_detail:
            return {'success': False, 'message': error_detail}

        lowered = response.text.lower()
        if (
            'parent.location' in lowered
            or 'window.location' in lowered
            or f'task-view-{task_id}' in lowered
            or 'success' in lowered
        ):
            return {'success': True, 'message': f"任务 {task_id} 修改请求已提交"}

        alert_match = re.search(r"alert\(['\"](.+?)['\"]\)", response.text)
        if alert_match:
            return {'success': False, 'message': alert_match.group(1)}

        return {'success': False, 'message': '无法解析服务器响应'}

    def verify_task_created(self, project_id: int, task_name: str, exact: bool = False) -> Optional[Dict[str, Any]]:
        """
        验证任务是否创建成功
        
        Args:
            project_id: 项目 ID
            task_name: 任务名称
            
        Returns:
            找到的任务信息，未找到返回 None
        """
        if not self._logged_in:
            return None
        
        try:
            # 获取项目任务列表
            api_url = f"{self.base_url}/biz/project-task-{project_id}.json"
            response = self.session.get(api_url, timeout=10)
            
            if response.status_code != 200:
                return None
            
            result = response.json()
            
            if 'data' in result and isinstance(result['data'], str):
                data = json.loads(result['data'])
            else:
                data = result.get('data', {})
            
            tasks = data.get('tasks', {})
            
            # 搜索任务
            for task_id, task in tasks.items():
                if isinstance(task, dict) and (
                    task.get('name', '') == task_name if exact else task_name in task.get('name', '')
                ):
                    return {
                        'id': task_id,
                        'name': task.get('name'),
                        'module': task.get('module'),
                        'assignedTo': task.get('assignedTo')
                    }
            
            return None
            
        except:
            return None

    def screenshot_task(self, task_id: int = None, task_name: str = None, project_id: int = None, screenshot_dir: Optional[str] = None) -> Optional[str]:
        """
        截图「我的任务」页面（利用当前已登录 session cookie）
        
        Args:
            task_id: 任务ID（兼容参数，不再使用）
            task_name: 任务名称（兼容参数，用于文件名）
            project_id: 项目ID（兼容参数，不再使用）
            screenshot_dir: 截图保存目录（默认: scripts/screenshots）
            
        Returns:
            截图文件路径，失败返回 None。
        """
        try:
            if screenshot_dir is None:
                screenshot_dir = get_artifact_dir('screenshots')
            os.makedirs(screenshot_dir, exist_ok=True)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            if task_name:
                safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '_', task_name)[:30]
                screenshot_path = os.path.join(screenshot_dir, f'zentao-task-{safe_name}-{timestamp}.png')
            else:
                screenshot_path = os.path.join(screenshot_dir, f'zentao-my-tasks-{timestamp}.png')

            # 导出 session cookie
            cookie_file = os.path.join(screenshot_dir, f'cookies-{timestamp}.json')
            cookies = []
            domain = self.base_url.split('/')[2]
            for cookie in self.session.cookies:
                cookies.append({
                    'name': cookie.name,
                    'value': cookie.value,
                    'domain': cookie.domain or domain,
                    'path': cookie.path or '/',
                    'secure': cookie.secure
                })
            with open(cookie_file, 'w') as f:
                json.dump(cookies, f)

            # 截图网址固定为「我的任务」页面
            screenshot_url = f"{self.base_url}/biz/my-task-openedBy.html"

            playwright_script = f'''
import sys, json
try:
    from playwright.sync_api import sync_playwright
    with open("{cookie_file}") as f:
        cookies = json.load(f)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={{"width": 1920, "height": 1080}})
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto("{screenshot_url}", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        page.screenshot(path="{screenshot_path}", full_page=True)
        browser.close()
    print("OK")
except ImportError:
    print("NO_PLAYWRIGHT")
    sys.exit(1)
except Exception as e:
    print(f"ERR: {{e}}")
    sys.exit(2)
'''
            python_exec = find_playwright_python()
            if not python_exec:
                print("⚠ Playwright 未安装或没有兼容的 Python 解释器，跳过截图。")
                return None
            result = subprocess.run(
                [python_exec, '-c', playwright_script],
                capture_output=True, text=True, timeout=45
            )
            if result.returncode == 0:
                return screenshot_path
            else:
                if 'NO_PLAYWRIGHT' in result.stdout:
                    print(f"⚠ Playwright 未安装或当前解释器不可用，跳过截图。当前 Python: {python_exec}; stdout: {result.stdout.strip()}")
                else:
                    print(f"✗ 截图失败: stdout={result.stdout.strip()} stderr={result.stderr.strip()}")
                return None
        except Exception as e:
            print(f"✗ 截图异常: {e}")
            return None

    def screenshot_task_list(self, screenshot_dir: Optional[str] = None) -> Optional[str]:
        """
        截图"我的任务"页面（利用当前已登录 session cookie）
        
        说明：导出当前 session 的 cookie，通过 Playwright 启动 headless 浏览器
        加载 cookie 后访问 /biz/my-task-openedBy.html 完成截图。
        返回截图文件路径，失败返回 None。
        
        前置条件：pip install playwright && playwright install chromium
        """
        try:
            if screenshot_dir is None:
                screenshot_dir = get_artifact_dir('screenshots')
            os.makedirs(screenshot_dir, exist_ok=True)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            screenshot_path = os.path.join(screenshot_dir, f'zentao-my-tasks-{timestamp}.png')

            # 将当前 session 的 cookie 导出为文件，供 Playwright 使用
            cookie_file = os.path.join(screenshot_dir, f'cookies-{timestamp}.json')
            cookies = []
            domain = self.base_url.split('/')[2]
            for cookie in self.session.cookies:
                cookies.append({
                    'name': cookie.name,
                    'value': cookie.value,
                    'domain': cookie.domain or domain,
                    'path': cookie.path or '/',
                    'secure': cookie.secure
                })
            with open(cookie_file, 'w') as f:
                json.dump(cookies, f)

            # 目标 URL：我的任务页面
            task_list_url = f"{self.base_url}/biz/my-task-openedBy.html"

            # 使用 Playwright 截图
            playwright_script = f'''
import sys, json, os
try:
    from playwright.sync_api import sync_playwright
    with open("{cookie_file}") as f:
        cookies = json.load(f)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={{"width": 1920, "height": 1080}})
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto("{task_list_url}", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)  # 等待动态内容加载
        page.screenshot(path="{screenshot_path}", full_page=True)
        browser.close()
    print("OK")
except ImportError:
    print("NO_PLAYWRIGHT")
    sys.exit(1)
except Exception as e:
    print(f"ERR: {{e}}")
    sys.exit(2)
'''
            python_exec = find_playwright_python()
            if not python_exec:
                print("⚠ Playwright 未安装或没有兼容的 Python 解释器，跳过截图。")
                return None

            result = subprocess.run(
                [python_exec, '-c', playwright_script],
                capture_output=True, text=True, timeout=45
            )
            if result.returncode == 0:
                print(f"✓ 截图已保存: {screenshot_path}")
                return screenshot_path
            else:
                stderr = result.stderr.strip()
                if 'NO_PLAYWRIGHT' in result.stdout:
                    print(f"⚠ Playwright 未安装，跳过截图。当前 Python: {python_exec}")
                else:
                    print(f"✗ 截图失败: {stderr}")
                return None

        except subprocess.TimeoutExpired:
            print("✗ 截图超时")
            return None
        except Exception as e:
            print(f"✗ 截图异常: {e}")
            return None


def check_user_permission(user_id: str) -> bool:
    """
    检查用户是否有权限使用禅道功能
    
    Args:
        user_id: 用户 open_id
        
    Returns:
        是否有权限
    """
    # 权限检查已禁用，所有用户均可使用
    return True


def format_project_list(projects: List[Dict[str, Any]]) -> str:
    """
    格式化项目列表为可读字符串
    
    Args:
        projects: 项目列表
        
    Returns:
        格式化后的字符串
    """
    if not projects:
        return "没有找到项目"
    
    lines = [
        "=" * 80,
        f"{'ID':<10} {'名称':<40} {'状态':<10} {'代号':<15}",
        "=" * 80
    ]
    
    for proj in projects:
        pid = str(proj.get('id', ''))[:9]
        name = str(proj.get('name', ''))[:38]
        status = str(proj.get('status', ''))[:9]
        code = str(proj.get('code', ''))[:14]
        lines.append(f"{pid:<10} {name:<40} {status:<10} {code:<15}")
    
    lines.append("=" * 80)
    lines.append(f"\n共找到 {len(projects)} 个项目")
    
    return "\n".join(lines)


def format_module_list(modules: List[Dict[str, Any]]) -> str:
    """
    格式化模块列表为可读字符串
    
    Args:
        modules: 模块列表
        
    Returns:
        格式化后的字符串
    """
    if not modules:
        return "该项目没有配置模块"
    
    lines = ["可用模块列表:", ""]
    
    for i, mod in enumerate(modules, 1):
        name = mod.get('name', '')
        mid = mod.get('id', '')
        lines.append(f"  {i}. {name} (ID: {mid})")
    
    return "\n".join(lines)


if __name__ == '__main__':
    # 简单的测试代码
    print("禅道公共库加载成功")
    print(f"默认禅道 URL: {ZentaoClient._get_default_url()}")
