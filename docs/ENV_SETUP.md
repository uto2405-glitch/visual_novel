# 환경변수 설정 — 토큰을 파일에 쓰지 않고 영구 등록하기

이 저장소는 **키·토큰을 어떤 파일에도 저장하지 않는다.** 코드는 오직 환경변수에서만 읽는다.
그런데 PowerShell 창에서 `$env:...` 로 설정한 값은 **그 창을 닫으면 사라진다.** 재부팅 후
"어제는 됐는데 오늘은 이미지 생성이 401 이다" 하는 조용한 실패가 대부분 여기서 나온다.
`setx` 로 한 번만 영구 등록하면 끝난다.

> 이 문서에는 실제 토큰 값이 하나도 없다. 앞으로도 넣지 않는다.

---

## 1. 이 프로젝트가 쓰는 환경변수

| 변수 | 쓰는 곳 | 없으면 | 필수? |
|---|---|---|---|
| `MAKEFUN_API_TOKEN` | `tools/makefun_client.py` — 이미지 생성 | 이미지 생성만 막힘(안내 메시지). 감상·검사·대화는 정상 | 이미지 생성을 할 때만 |
| `XAI_API_KEY` | `tools/xai_client.py` — 그록 API(예비 경로) | 그록 API 경로만 막힘. 로컬 LLM 이 기본이라 보통 불필요 | 아니오 |
| `LOCAL_LLM_URL` | `tools/local_llm.py` — 로컬 LLM 주소 | 매니페스트 `talk.base_url` → 없으면 `http://127.0.0.1:8080/v1` | 아니오(주소를 바꿀 때만) |

`LOCAL_LLM_URL` 은 비밀이 아니라 그냥 주소다. 나머지 둘은 **비밀값**이다.

발급처
- MakeFun: makefun.ai → Account → API Token
- xAI: console.x.ai (SuperGrok 구독과는 **별도 결제 트랙**이다. 구독에 API 크레딧이 포함되지 않는다.)

---

## 2. 영구 등록 (권장) — `setx`

PowerShell 이나 cmd 어느 쪽에서 해도 된다. **관리자 권한 불필요**(내 사용자 계정에만 등록된다).

```powershell
setx MAKEFUN_API_TOKEN "여기에_발급받은_토큰"
setx LOCAL_LLM_URL "http://127.0.0.1:8080/v1"
```

**중요 — 등록 직후 지금 창에서는 아직 안 보인다.** `setx` 는 새 프로세스부터 적용된다.
등록한 PowerShell 창을 **닫고 새로 연 뒤** 스튜디오를 기동해야 한다.

### 확인 (값을 화면에 띄우지 않고)

```powershell
# 설정됐는지만 — 값은 출력하지 않는다
if ($env:MAKEFUN_API_TOKEN) { "설정됨 ($($env:MAKEFUN_API_TOKEN.Length)자)" } else { "미설정" }
```

또는 한 번에:

```
python tools/doctor.py
```

`doctor` 는 설정 여부와 길이만 보여주고 값은 절대 출력하지 않는다.

### 알아둘 것
- `setx` 는 값이 **1024자를 넘으면 잘라서 저장한다.** 토큰이 길면 등록 후 길이를 확인하자.
- 값은 레지스트리 `HKCU\Environment` 에 **평문**으로 들어간다. 파일에 두는 것보다 낫지만
  "암호화되어 저장된다"는 뜻은 아니다. 공용 PC 에서는 세션 전용(3번)을 쓰자.
- `setx /M` 은 시스템 전체(모든 사용자)에 등록한다. **개인 PC 에서는 쓰지 말 것** — 필요 없다.
- 이미 켜져 있던 프로그램(예: 먼저 띄워둔 llama-server, VS Code)은 재시작해야 새 값을 본다.

---

## 3. 이번 세션만 (공용 PC·임시 테스트)

```powershell
$env:MAKEFUN_API_TOKEN = "여기에_발급받은_토큰"     # PowerShell
```
```cmd
set MAKEFUN_API_TOKEN=여기에_발급받은_토큰          REM cmd
```

창을 닫으면 사라진다. 남기고 싶지 않을 때는 이쪽이 정답이다.

---

## 4. 값 변경 · 폐기

```powershell
setx MAKEFUN_API_TOKEN "새_토큰"        # 덮어쓰기 (새 창부터 적용)
```

**완전히 지우려면** (`setx VAR ""` 는 빈 값으로 남을 뿐 삭제가 아니다):

```powershell
reg delete "HKCU\Environment" /F /V MAKEFUN_API_TOKEN
$env:MAKEFUN_API_TOKEN = $null        # 지금 창에서도 즉시 제거
```

새 창부터 반영된다.

---

## 5. 유출했을 때 (순서가 중요하다)

1. **먼저 발급처에서 그 토큰을 폐기하고 새로 발급한다.** 파일에서 지우는 게 먼저가 아니다 —
   이미 노출된 값은 지워도 계속 유효하다.
2. 파일에서 값을 제거하고 환경변수 참조로 바꾼다.
3. 저장소 전체를 다시 훑는다:
   ```
   python tools/secret_scan.py
   python tools/check_protocol.py     # A8 이 xai- 패턴을 판정
   ```
4. **커밋된 적이 있으면** 파일을 고쳐도 git 이력에는 남아 있다. 이 경우 반드시 사용자에게
   보고한다(이력 재작성은 되돌릴 수 없는 작업이라 에이전트가 임의로 하지 않는다).

---

## 6. 하지 말 것

- `.env` 파일에 쓰기 — `.gitignore` 에 있어도 **금지**다. 근거: 2026-07 Grok Build CLI 가
  `.env` 의 키를 평문으로 서버에 전송한 사고.
- 서드파티 CLI·에이전트 도구에 토큰 붙여넣기.
- 매니페스트·장면 JSON·문서·스크립트·주석에 값 적기. 매니페스트에는 **변수 이름만** 적는다:
  ```json
  "api": { "base_url": "https://makefun.ai", "token_env": "MAKEFUN_API_TOKEN" }
  ```
- 화면 공유·캡처 중에 `echo $env:MAKEFUN_API_TOKEN` 실행하기.

---

## 7. 관련 문서

- [PHONE_TUTORIAL.md](PHONE_TUTORIAL.md) — 폰에서 LAN 접속·PWA 설치
- [RECOVERY_RUNBOOK.md](RECOVERY_RUNBOOK.md) — 재설치·복구 시 환경변수 재등록 순서
- [PRIVACY_HOSTING.md](PRIVACY_HOSTING.md) — 감상본을 밖에 올릴 때의 위험
