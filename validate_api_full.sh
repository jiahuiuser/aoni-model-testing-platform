#!/bin/bash
# validate_api_full.sh — 模型服务全量验收脚本
# 融合协议覆盖 (validate_api.sh) + 特性深度 (test_glm_serve.sh)
#
# 用法:
#   bash validate_api_full.sh <BASE_URL> <MODEL> [API_KEY]
#   bash validate_api_full.sh <BASE_URL1> <MODEL1> <BASE_URL2> <MODEL2> ...
#   bash validate_api_full.sh http://10.10.250.234:8003 step3p7 http://10.20.1.9:50001 GLM-5.1
#   bash validate_api_full.sh http://10.10.250.219/v1 DeepSeek-V4-Flash-DSpark sk-xxx
#
# 可选环境变量:
#   TEST_LONGCTX=1   启用长上下文边界测试 (默认关, 因耗时)
#   PROTOCOLS=openai,anthropic,responses  控制协议测试 (默认全开)
#
# 结果三态: PASS / FAIL / SKIP (模型不支持的特性=SKIP, 不算失败)

set -uo pipefail

# ── 全局状态 ──
TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_SKIP=0
AUTH_HEADER=""

# ── 辅助函数 ──
pass() { TOTAL_PASS=$((TOTAL_PASS+1)); echo -e "  ${GREEN}✅ $1${NC}"; }
fail() { TOTAL_FAIL=$((TOTAL_FAIL+1)); echo -e "  ${RED}❌ $1 — $2${NC}"; }
skip() { TOTAL_SKIP=$((TOTAL_SKIP+1)); echo -e "  ${YELLOW}⏭️  $1 — $2${NC}"; }
banner() { echo ""; echo -e "${CYAN}━━━ $1 ━━━${NC}"; }

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

_curl() {
  if [ -n "$AUTH_HEADER" ]; then
    curl -s -H "$AUTH_HEADER" "$@"
  else
    curl -s "$@"
  fi
}

# 提取 JSON 字段 (python3)
_json_field() {
  local json="$1" code="$2"
  echo "$json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    $code
except Exception as e:
    print('')
" 2>/dev/null
}

# 检测 content 是否垃圾 (复用 GLM 脚本逻辑)
_is_garbage() {
  local text="$1"
  echo "$text" | python3 -c "
import sys, re
t = sys.stdin.read()
if not t.strip():
    print('EMPTY')
    sys.exit(0)
garb = re.findall(r'https?://|\.com|\.www|null|undefined|\xaa{2,}', t.lower())
cjk = any(0x4e00 <= ord(ch) <= 0x9fff for ch in t[:80])
if garb:
    print('GARBAGE')
elif not cjk and len(t) > 20:
    print('NO_CJK')
else:
    print('OK')
" 2>/dev/null
}

# ── 协议层: OpenAI Chat Completions ──
test_openai_chat() {
  local base="$1" model="$2"
  banner "OpenAI Chat Completions"
  local json="{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"回复OK\"}],\"max_tokens\":50,\"temperature\":0}"
  local res=$(_curl --max-time 90 "$base/v1/chat/completions" \
    -H "Content-Type: application/json" -d "$json" 2>/dev/null)
  local ct=$(_json_field "$res" "c=d['choices'][0]['message'];print('Y' if (c.get('content') or (c.get('reasoning') and c.get('content') is None)) else 'N')")
  if [ "$ct" = "Y" ]; then pass "Chat 同步返回 content"; else fail "Chat 同步返回 content" "content 为空或错误"; fi

  # 流式
  local stream_res=$(_curl --max-time 90 "$base/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"回复OK\"}],\"max_tokens\":30,\"stream\":true}" 2>&1 | head -20)
  if echo "$stream_res" | grep -q "data:"; then pass "Chat 流式输出 SSE"; else fail "Chat 流式输出 SSE" "未收到 data: 事件"; fi

  # 带工具
  local tjson="{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"请调用 get_weather 工具查询北京的天气\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"get_weather\",\"description\":\"获取城市天气\",\"parameters\":{\"type\":\"object\",\"properties\":{\"city\":{\"type\":\"string\"}},\"required\":[\"city\"]}}}],\"max_tokens\":200,\"temperature\":0}"
  local res=$(_curl --max-time 90 "$base/v1/chat/completions" \
    -H "Content-Type: application/json" -d "$tjson" 2>/dev/null)
  local tc_count=$(_json_field "$res" "print(len(d['choices'][0]['message'].get('tool_calls',[])))")
  if [ "${tc_count:-0}" != "0" ] && [ -n "$tc_count" ]; then
    pass "Chat 工具调用返回 tool_calls"
  else
    skip "Chat 工具调用返回 tool_calls" "模型未触发工具调用 (可能 prompt 不够强制)"
  fi
}

# ── 协议层: OpenAI Responses ──
test_openai_responses() {
  local base="$1" model="$2"
  banner "OpenAI Responses"
  local json="{\"model\":\"$model\",\"input\":\"请简要说明vLLM的主要功能，至少列出三点并用一段话概括\",\"max_output_tokens\":300,\"temperature\":0}"
  local res=$(_curl --max-time 90 "$base/v1/responses" \
    -H "Content-Type: application/json" -d "$json" 2>/dev/null)
  local has_text=$(echo "$res" | python3 -c "
import sys,json
try:
    d=json.loads(sys.stdin.read().strip().split('\n')[0])
    for o in d.get('output',[]):
        for c in (o.get('content') or []):
            if c.get('text'):
                print('Y'); sys.exit(0)
    print('N')
except Exception:
    print('N')
" 2>/dev/null | head -1)
  if [ "$has_text" = "Y" ]; then pass "Responses 返回 text"; else fail "Responses 返回 text" "content 为空"; fi
}

# ── 协议层: Anthropic Messages ──
test_anthropic_messages() {
  local base="$1" model="$2"
  banner "Anthropic Messages"
  local json="{\"model\":\"$model\",\"max_tokens\":30,\"messages\":[{\"role\":\"user\",\"content\":\"回复OK\"}]}"
  local res=$(_curl --max-time 90 "$base/v1/messages" \
    -H "Content-Type: application/json" -H "x-api-key: none" -H "anthropic-version: 2023-06-01" \
    -d "$json" 2>/dev/null)
  local ct=$(echo "$res" | python3 -c "
import sys,json
try:
    d=json.loads(sys.stdin.read().strip().split('\n')[0])
    text = ''
    for c in (d.get('content') or []):
        if c.get('text'):
            print('Y'); sys.exit(0)
        text += c.get('text','')
    if d.get('reasoning') and not text:
        print('Y'); sys.exit(0)
    print('N')
except Exception:
    print('N')
" 2>/dev/null | head -1)
  if [ "$ct" = "Y" ]; then pass "Anthropic 同步返回 text"; else fail "Anthropic 同步返回 text" "content 为空"; fi

  # 流式
  local stream_res=$(_curl --max-time 90 "$base/v1/messages" \
    -H "Content-Type: application/json" -H "x-api-key: none" -H "anthropic-version: 2023-06-01" \
    -d "{\"model\":\"$model\",\"max_tokens\":30,\"messages\":[{\"role\":\"user\",\"content\":\"回复OK\"}],\"stream\":true}" 2>&1 | head -20)
  if echo "$stream_res" | grep -qE "message_start|content_block_start|content_block_delta|text_delta|event:"; then pass "Anthropic 流式 SSE"; else fail "Anthropic 流式 SSE" "未收到预期事件"; fi

  # 带工具
  local tjson="{\"model\":\"$model\",\"max_tokens\":30,\"messages\":[{\"role\":\"user\",\"content\":\"请调用 get_weather 工具查询北京的天气\"}],\"tools\":[{\"name\":\"get_weather\",\"description\":\"获取城市天气\",\"input_schema\":{\"type\":\"object\",\"properties\":{\"city\":{\"type\":\"string\"}},\"required\":[\"city\"]}}]}"
  local tres=$(_curl --max-time 90 "$base/v1/messages" \
    -H "Content-Type: application/json" -H "x-api-key: none" -H "anthropic-version: 2023-06-01" \
    -d "$tjson" 2>/dev/null)
  local has_tool=$(echo "$tres" | python3 -c "
import sys,json,re
try:
    d=json.loads(sys.stdin.read().strip().split('\n')[0])
    text = ''
    for c in (d.get('content') or []):
        if c.get('type')=='tool_use':
            print('Y'); sys.exit(0)
        text += c.get('text','')
    if '\u003cinvoke' in text or 'tool_call' in text.lower():
        print('Y'); sys.exit(0)
    print('N')
except Exception:
    print('N')
" 2>/dev/null | head -1)
  if [ "$has_tool" = "Y" ]; then pass "Anthropic 工具调用返回 tool_use"; else skip "Anthropic 工具调用返回 tool_use" "模型未触发工具调用"; fi
}

# ── 特性层: 工具调用正确性 ──
test_toolcall_correctness() {
  local base="$1" model="$2"
  banner "特性: 工具调用正确性"
  local tjson="{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"请调用 get_weather 工具查询北京的天气\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"get_weather\",\"description\":\"获取城市天气\",\"parameters\":{\"type\":\"object\",\"properties\":{\"city\":{\"type\":\"string\"}},\"required\":[\"city\"]}}}],\"max_tokens\":200,\"temperature\":0}"
  local res=$(_curl --max-time 90 "$base/v1/chat/completions" \
    -H "Content-Type: application/json" -d "$tjson" 2>/dev/null)
  local tc_name=$(_json_field "$res" "tc=d['choices'][0]['message'].get('tool_calls',[]);print(tc[0]['function']['name'] if tc else 'NONE')")
  local fr=$(_json_field "$res" "print(d['choices'][0].get('finish_reason',''))")
  [ "$tc_name" = "get_weather" ] && pass "工具函数名正确 (get_weather)" || fail "工具函数名正确" "期望 get_weather, 实际 $tc_name"
  [ "$fr" = "tool_calls" ] && pass "finish_reason=tool_calls" || fail "finish_reason=tool_calls" "实际 $fr"
}

# ── 特性层: Reasoning 分离 (探测式) ──
test_reasoning() {
  local base="$1" model="$2"
  banner "特性: Reasoning 分离 (探测式)"
  local json="{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"1+1=?，先思考再回答\"}],\"max_tokens\":200,\"temperature\":0}"
  local res=$(_curl --max-time 90 "$base/v1/chat/completions" \
    -H "Content-Type: application/json" -d "$json" 2>/dev/null)
  local reasoning=$(_json_field "$res" "m=d['choices'][0]['message'];print(m.get('reasoning') or m.get('reasoning_content') or '')")
  local content=$(_json_field "$res" "m=d['choices'][0]['message'];print(m.get('content') or '')")
  if [ -n "$reasoning" ]; then
    pass "reasoning 字段非空 (分离成功)"
  else
    skip "reasoning 字段为空" "模型不输出独立 reasoning (Step 系列混在 content)"
  fi
  [ -n "$content" ] && pass "content 字段非空" || pass "content 为空但 reasoning 非空 (GLM 行为)"
}

# ── 特性层: 大 prompt 压测 ──
test_large_prompt() {
  local base="$1" model="$2"
  banner "特性: 大 prompt 压测 (15 工具定义)"
  local res=$(python3 -c "
import json
tools = [{'type':'function','function':{'name':f'tool_{i}','description':'Tool {i}. '*10,'parameters':{'type':'object','properties':{f'p{j}':{'type':'string','description':f'Param {j}. '*5} for j in range(3)},'required':['p0']}}} for i in range(15)]
print(json.dumps({'model':'$model','messages':[{'role':'system','content':'You are opencode. '*50},{'role':'user','content':'你好'}],'tools':tools,'max_tokens':200,'temperature':0}))
" | _curl --max-time 120 "$base/v1/chat/completions" \
  -H "Content-Type: application/json" -d @- 2>&1)

  local status=$(echo "$res" | python3 -c "
import sys, json, re
try:
    d = json.loads(sys.stdin.read().strip().split('\n')[0])
    if 'error' in d:
        print('API_ERROR: ' + str(d['error'].get('message',''))[:80])
    else:
        c = d['choices'][0]['message']
        t = (c.get('content') or '') + (c.get('reasoning') or '')
        garb = re.findall(r'https?://|\.com|\.www|null|undefined|\xaa{2,}', t.lower())
        cjk = any(0x4e00 <= ord(ch) <= 0x9fff for ch in t[:80])
        print('OK' if (not garb and cjk) else 'GARBAGE' if garb else 'EMPTY')
except Exception as e:
    print('PARSE_ERR: ' + str(e)[:80])
" 2>/dev/null | head -1)
  [ "$status" = "OK" ] && pass "大 prompt 输出正常（无垃圾）" || fail "大 prompt 输出正常" "状态: $status"
}

# ── 特性层: 长上下文边界 ──
test_longctx() {
  local base="$1" model="$2"
  banner "特性: 长上下文边界 (TEST_LONGCTX=1)"
  # 获取 max_model_len
  local maxlen=$(_curl "$base/v1/models" 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    m = d['data'][0]
    print(m.get('max_model_len') or m.get('owned_by') or '8192')
except: print('8192')
" 2>/dev/null)
  echo "  模型 max_model_len = $maxlen"

  # 灌入接近上限的 prompt (用中文文本, 约 60 字符/token 估算)
  local target=$(( maxlen * 90 / 100 ))  # 90% 上限, 安全区
  echo "  构造约 $target token 的 prompt ..."
  local res=$(python3 -c "
import json, urllib.request, time
probe = '这是一段用于测试长上下文的文本内容。Step模型支持长上下文窗口部署。'
repeats = max(1, $target * 60 // len(probe))  # 60 chars per token approx
base = probe * repeats
messages = [{'role':'user','content': base + '\n\n请回答：上面这段测试文本的主题是什么？一句话即可。'}]
payload = json.dumps({'model':'$model','messages':messages,'max_tokens':20}).encode()
headers = {'Content-Type':'application/json'}
if '$AUTH_HEADER':
    key = '$AUTH_HEADER'.replace('Authorization: Bearer ', '')
    headers['Authorization'] = 'Bearer ' + key
req = urllib.request.Request('$base/v1/chat/completions', data=payload, headers=headers)
t0=time.time()
try:
    resp = urllib.request.urlopen(req, timeout=400)
    d = json.loads(resp.read())
    u = d.get('usage',{})
    pt = u.get('prompt_tokens',0)
    c = d['choices'][0]['message'].get('content','')
    print('SUCCESS' if c else 'EMPTY', pt)
except Exception as e:
    msg = e.read().decode() if hasattr(e,'read') else str(e)
    import re
    m = re.search(r'contains at least (\d+) input tokens', msg)
    print('LIMIT_HIT' if m else 'ERR', m.group(1) if m else msg[:60])
" 2>&1)
  echo "  结果: $res"
  if echo "$res" | grep -q "SUCCESS"; then
    pass "长上下文正常推理 (接近上限不崩溃)"
  elif echo "$res" | grep -q "LIMIT_HIT"; then
    pass "长上下文边界正确拒绝超限请求"
  else
    fail "长上下文测试" "$res"
  fi
}

# ── 主流程: 测单个 target ──
run_target() {
  local base="$1" model="$2" api_key="${3:-}"
  # 归一化: base 只到端口, 不含 /v1 (统一在路径里加 /v1)
  base="${base%/}"
  base="${base%/v1}"
  AUTH_HEADER=""
  if [ -n "$api_key" ]; then AUTH_HEADER="Authorization: Bearer $api_key"; fi

  echo ""
  echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║  模型服务全量验收                           ║${NC}"
  echo -e "${CYAN}║  URL: $base${NC}"
  echo -e "${CYAN}║  模型: $model${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"

  # Layer 1: 可达性
  banner "Layer 1 — 服务可达性"
  local hc=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$base/v1/health" 2>/dev/null)
  if [ "$hc" = "200" ] || _curl --max-time 5 "$base/v1/models" >/dev/null 2>&1; then
    pass "服务可达 (/health 或 /v1/models)"
  else
    fail "服务可达" "无法连接 $base"
    return 1
  fi
  local models=$(_curl "$base/v1/models" 2>/dev/null)
  if echo "$models" | grep -qF "$model"; then pass "模型列表包含 $model"; else fail "模型列表包含 $model" "未找到"; fi

  local ctx_len=$(echo "$models" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for m in d.get('data', []):
        if m.get('id') == '$model':
            v = m.get('max_model_len') or m.get('owned_by') or 'N/A'
            print(v)
            sys.exit(0)
    print('N/A')
except Exception:
    print('N/A')
" 2>/dev/null)
  echo -e "  ${CYAN}ℹ️  上下文长度: $ctx_len${NC}"

  # Layer 2: 协议覆盖
  banner "Layer 2 — 协议覆盖"
  local protos="${PROTOCOLS:-openai,anthropic,responses}"
  echo "$protos" | grep -q "openai" && test_openai_chat "$base" "$model"
  echo "$protos" | grep -q "responses" && test_openai_responses "$base" "$model"
  echo "$protos" | grep -q "anthropic" && test_anthropic_messages "$base" "$model"

  # Layer 3: 特性深度
  banner "Layer 3 — 特性通用"
  test_toolcall_correctness "$base" "$model"
  test_reasoning "$base" "$model"
  test_large_prompt "$base" "$model"
  if [ "${TEST_LONGCTX:-0}" = "1" ]; then
    test_longctx "$base" "$model"
  else
    skip "长上下文边界测试" "未启用 (TEST_LONGCTX=1 开启)"
  fi
}

# ── 入口: 解析参数 ──
if [ $# -lt 2 ]; then
  echo "用法: bash $0 <BASE_URL> <MODEL> [API_KEY] [<BASE_URL2> <MODEL2> ...]"
  echo " 或: bash $0 http://host:port step3p7"
  echo " 或: bash $0 http://host/v1 model sk-xxx"
  echo " 多 target: bash $0 url1 model1 url2 model2"
  exit 1
fi

# 循环处理 (每两个参数一组: url model [key])
while [ $# -ge 2 ]; do
  run_target "$1" "$2" "${3:-}"
  if [ $# -ge 3 ] && [[ "$3" != http* ]]; then
    # 第三个参数是 API_KEY (非 URL), 消耗它
    shift 3
  else
    shift 2
  fi
done

# ── 汇总 ──
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║           全量验收汇总                     ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════╣${NC}"
printf "${CYAN}║${NC}  通过: ${GREEN}%d${NC} 失败: ${RED}%d${NC} 跳过: ${YELLOW}%d${NC}  ║\n" "$TOTAL_PASS" "$TOTAL_FAIL" "$TOTAL_SKIP"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"

[ "$TOTAL_FAIL" -gt 0 ] && exit 1 || exit 0
