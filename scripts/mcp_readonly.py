"""Minimal read-only MCP bridge; never executes order, claim, or redemption tools."""

import json
import os
import time
import urllib.error
import urllib.request


ALLOWED = {'now-time-info', 'query-nearby-stores', 'query-meals', 'query-meal-detail',
           'list-nutrition-foods', 'query-store-coupons', 'query-my-coupons', 'available-coupons',
           'calculate-price'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ToolBusinessError(ValueError):
    """One candidate failed business validation; other fixed-basket plans may work."""


class MCP:
    def __init__(self, max_retries=2):
        self.token = os.environ.get('MCD_MCP_TOKEN', '').strip()
        if not self.token or self.token.startswith('${'):
            raise ValueError('未配置 MCD_MCP_TOKEN。请在本机私有环境设置后运行 doctor，或使用宿主现有的麦当劳连接器')
        if type(max_retries) is not int or not 0 <= max_retries <= 2:
            raise ValueError('网络重试次数应为 0–2')
        self.max_retries = max_retries
        self.retry_count = 0
        self.session = None
        self.protocol = None
        self.counter = 0
        self.opener = urllib.request.build_opener(NoRedirect)

    def rpc(self, method, params=None, notification=False):
        if method not in ('initialize', 'notifications/initialized', 'tools/list', 'tools/call'):
            raise ValueError('本程序只允许只读 MCP 会话与工具请求')
        if method == 'tools/call' and (not isinstance(params, dict) or params.get('name') not in ALLOWED):
            raise ValueError('本程序仅允许餐品、门店、优惠查询和核价')
        self.counter += 1
        payload = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            payload['params'] = params
        if not notification:
            payload['id'] = self.counter
        headers = {'Authorization': 'Bearer ' + self.token,
                   'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        if self.protocol:
            headers['MCP-Protocol-Version'] = self.protocol
        request = urllib.request.Request('https://mcp.mcd.cn', data=json.dumps(payload).encode(), headers=headers)
        for attempt in range(self.max_retries + 1):
            try:
                return self.request(request, payload, notification)
            except urllib.error.HTTPError as exc:
                code = exc.code
                exc.close()
                if code in (500, 502, 503, 504) and attempt < self.max_retries:
                    self.retry_count += 1
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                hints = {401: 'Token 无效或已过期，请在官方控制台更新本机凭据并运行 doctor',
                         403: '当前账号或 Token 无访问权限，请检查官方控制台权限',
                         429: '已触发限流，请按官方提示稍后重试，不自动重发',
                         404: '服务或会话不可用，请运行 doctor 后重新执行',
                         400: '请求参数不符合当前接口，请核对实际 schema'}
                raise ValueError(f'MCP HTTP {code}；' + hints.get(code, '服务暂时不可用，有限重试已结束，请稍后重新执行')) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt < self.max_retries:
                    self.retry_count += 1
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise ValueError('MCP 网络请求失败，有限重试已结束。请检查网络后运行 doctor；不会改用模拟数据或重抽餐单') from None

    def request(self, request, payload, notification):
        try:
            with self.opener.open(request, timeout=35) as response:
                self.session = response.headers.get('Mcp-Session-Id', self.session)
                content_type = response.headers.get('Content-Type', '')
                if notification:
                    return None
                if 'text/event-stream' in content_type:
                    data_lines = []
                    for raw_line in response:
                        line = raw_line.decode('utf-8').rstrip('\r\n')
                        if line.startswith('data:'):
                            data_lines.append(line[5:].lstrip())
                        elif not line and data_lines:
                            event = json.loads('\n'.join(data_lines))
                            data_lines = []
                            if event.get('id') == payload['id']:
                                return self.unwrap(event)
                    raise ValueError('MCP 流未返回对应请求的结果')
                message = json.loads(response.read().decode('utf-8'))
                if message.get('id') != payload['id']:
                    raise ValueError('MCP 响应与当前请求不匹配')
                return self.unwrap(message)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError('MCP 返回格式无法解析，请运行 doctor 检查服务；本轮停止，不使用其中的金额') from None

    @staticmethod
    def unwrap(message):
        if 'error' in message:
            raise ValueError(f"MCP 协议错误 {message['error'].get('code', 'unknown')}；请核对 schema")
        return message.get('result', {})

    def connect(self):
        result = self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                        'clientInfo': {'name': 'mcd-random-meal', 'version': '0.1.0'}})
        self.protocol = result.get('protocolVersion', '2025-03-26')
        self.rpc('notifications/initialized', notification=True)

    def tools(self):
        result, cursor, seen = [], None, set()
        for _ in range(10):
            page = self.rpc('tools/list', {'cursor': cursor} if cursor else {})
            result.extend(t for t in page.get('tools', []) if t.get('name') in ALLOWED)
            cursor = page.get('nextCursor')
            if not cursor:
                return result
            if cursor in seen:
                break
            seen.add(cursor)
        raise ValueError('工具清单分页未结束，停止本轮')

    def call(self, name, arguments):
        if name not in ALLOWED:
            raise ValueError('本程序仅允许餐品、门店、优惠查询和核价')
        return self.rpc('tools/call', {'name': name, 'arguments': arguments})


def tool_data(result):
    if result.get('isError'):
        raise ToolBusinessError('此方案被 MCP 工具拒绝；不使用失败响应中的金额')
    if isinstance(result.get('structuredContent'), dict):
        payload = result['structuredContent']
    else:
        payload = None
        decoder = json.JSONDecoder()
        for block in result.get('content', []):
            if block.get('type') != 'text':
                continue
            text = block.get('text', '')
            for index, char in enumerate(text):
                if char == '{':
                    try:
                        candidate, _ = decoder.raw_decode(text[index:])
                        if isinstance(candidate, dict) and ('data' in candidate or 'success' in candidate):
                            payload = candidate
                            break
                    except json.JSONDecodeError:
                        continue
            if payload is not None:
                break
    if payload is None:
        raise ValueError('未找到明确成功的业务响应，请检查当前工具返回结构')
    if payload.get('success') is not True:
        raise ToolBusinessError('此方案业务校验失败；不使用失败响应中的金额')
    return payload


def pointer(document, path):
    if not path.startswith('/'):
        raise ValueError('金额路径使用 JSON Pointer，例如 /data/totalPrice')
    current = document
    for part in path[1:].split('/'):
        key = part.replace('~1', '/').replace('~0', '~')
        current = current[int(key)] if isinstance(current, list) else current[key]
    return current
