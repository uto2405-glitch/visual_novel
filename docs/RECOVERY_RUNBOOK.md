# 재해 복구 런북 — 고장났을 때 순서대로

당황해서 순서를 틀리면 살릴 수 있던 것도 날아간다. 증상별로 **무엇을 먼저 할지**만 적었다.

## 0. 어떤 상황이든 첫 두 줄

```
python tools/doctor.py          # 무엇이 깨졌는지 30초 안에 좁힌다 (읽기 전용)
python tools/backup_project.py verify   # 원본이 성한지 (sha256 대조)
```

**아직 아무것도 지우거나 덮어쓰지 마라.** 진단이 먼저다.

---

## 1. 무엇이 백업되고, 무엇이 안 되는가 (가장 중요)

`python tools/backup_project.py snapshot` 이 만드는 것:

| 파일 | 내용 |
|---|---|
| `backups/project_<시각>.zip` | **`project/` 폴더만** — 매니페스트·장면 JSON·스토리라인 |
| `backups/manifest_<시각>.json` | `project/` **와** `images/` 전체의 sha256 체크섬 목록 |

> ### ⚠ `images/` 는 zip 에 들어가지 않는다
> 백업 도구는 이미지의 **체크섬만 기록**한다(대용량이라서). 즉:
> - 이미지가 손상되면 **탐지는 된다.**
> - 이미지가 사라지면 **이 백업으로는 복구되지 않는다.**
>
> `.gitignore` 가 `images/raw/` 를 제외하므로 **git 도 이미지 백업이 아니다.**
> **`images/` 폴더는 반드시 따로 복사해 두어야 한다** (외장 디스크·다른 드라이브).
> 승인된 컷은 다시 만들 수 없다 — 같은 프롬프트로도 같은 그림은 나오지 않는다.

권장 습관: 승인 도장을 몇 장 찍은 날에는
```
python tools/backup_project.py snapshot
```
을 돌리고, 달마다 `images/` 를 통째로 외부 매체에 복사한다.

---

## 2. 증상별 대처

### A. 재부팅했더니 이미지 생성이 401 / "환경변수가 없습니다"

환경변수가 **그 창에서만** 설정돼 있었다. 값 자체는 멀쩡하다.

```
python tools/doctor.py          # [환경변수] 항목 확인
```
→ `setx` 로 영구 등록: **[ENV_SETUP.md](ENV_SETUP.md)** 2번.
등록 후 **PowerShell 창을 닫고 새로 열어야** 적용된다.

### B. 로컬 LLM 이 응답하지 않음 (스토리·프롬프트·대화 탭이 막힘)

```
python tools/local_llm.py       # ON/OFF 와 주소를 알려준다
```
- OFF → `powershell -ExecutionPolicy Bypass -File start_studio.ps1` (LLM 까지 같이 켠다)
- 직접 켜기 → `powershell -File c:\Users\USER\claude\local_llm\runtime\serve.ps1`
- 모델 적재에 수십 초가 걸린다. 바로 안 뜬다고 여러 번 켜지 마라 —
  `serve.ps1` 은 기존 프로세스를 죽이고 다시 띄우므로 처음부터 다시 로딩한다.
- 주소가 이상하면 `LOCAL_LLM_URL` 환경변수 또는 매니페스트 `talk.base_url` 을 확인한다.

### C. 장면 파일 하나가 깨졌다 (검사기 A1 FAIL, 뷰어에서 그 장면만 사라짐)

웹 스튜디오는 손상 장면을 건너뛰고 살아남도록 되어 있다. 그 한 파일만 되살리면 된다.

```powershell
# 1) 최신 백업을 임시 폴더에 푼다 (저장소를 직접 덮어쓰지 않는다)
$tmp = "$env:TEMP\vn_restore"
New-Item -ItemType Directory -Force $tmp | Out-Null
Expand-Archive -Path "backups\project_20260824_224601.zip" -DestinationPath $tmp -Force

# 2) 필요한 파일 하나만 눈으로 확인하고 되돌린다
Get-Content "$tmp\project\scenes\SCENE-003.json" -TotalCount 20
Copy-Item "$tmp\project\scenes\SCENE-003.json" "project\scenes\SCENE-003.json"

# 3) 확인
python tools/check_protocol.py --scene SCENE-003
```

`backups\project_*.zip` 의 파일 경로는 `project/...` 로 저장돼 있다.

### D. `project/` 폴더 전체를 날렸다

```powershell
$tmp = "$env:TEMP\vn_restore"
Expand-Archive -Path "backups\project_<가장최신>.zip" -DestinationPath $tmp -Force
Copy-Item "$tmp\project" "." -Recurse -Force
python tools/check_protocol.py
python tools/backup_project.py verify
```

`verify` 가 `✗ 누락` 으로 `images/...` 를 잔뜩 뱉으면 **이미지는 별도 복구가 필요**하다(1번 참고).

### E. `verify` 가 "변경/손상"을 보고한다

두 경우다.
- **내가 고친 것**(장면 편집·새 이미지 승인) → 정상이다. `snapshot` 을 다시 떠서 기준을 갱신한다.
- **아무것도 안 했는데 바뀜** → 비트로트나 디스크 문제일 수 있다.
  그 파일을 백업본과 바이트 비교하고, 디스크 상태를 점검한다. **인화 주문 직전에 반드시 확인할 것.**

### F. 승인된 장면의 이미지 원본이 사라졌다

`doctor` 의 `[프로젝트] 선택 이미지 존재` 항목이 잡아 준다.
1. 외부 백업에서 `images/raw/<SCENE-ID>/` 를 복원한다. — 가능하면 여기서 끝난다.
2. 복원할 사본이 정말 없다면, 그 장면은 승인을 되돌리고 다시 만드는 수밖에 없다:
   ```
   python tools/advance_scene.py revise SCENE-00X IMAGE --note "원본 소실"
   ```
   (같은 프롬프트로 다시 생성해도 같은 그림은 나오지 않는다. 그래서 1번이 중요하다.)

### G. 토큰이 유출된 것 같다

**순서가 중요하다 — 폐기가 먼저다.**
1. 발급처에서 해당 토큰 **폐기 후 재발급**.
2. `python tools/secret_scan.py` 로 저장소 전체 확인 (실제 값은 출력되지 않는다).
3. `python tools/check_protocol.py` 의 A8 확인.
4. 새 토큰을 `setx` 로 등록 → **[ENV_SETUP.md](ENV_SETUP.md)** 5번.
5. 커밋된 적이 있으면 파일을 고쳐도 이력에 남는다. 이 경우 이력 처리는 되돌릴 수 없으므로
   에이전트가 임의로 하지 않고 사용자가 결정한다.

---

## 3. PC 교체 · 완전 재설치 순서

순서를 지키면 한 번에 끝난다.

1. **Python 3.9+ 설치** — 설치 시 "Add to PATH" 체크.
   ```
   python --version
   ```
2. **Pillow 설치** (인화 마스터·감상본 용량 최적화에 필요. 없어도 나머지는 동작한다.)
   ```
   python -m pip install Pillow
   ```
3. **저장소 복원** — 코드·문서·템플릿. (git 저장소가 있으면 거기서, 없으면 백업 사본에서.)
4. **`project/` 복원** — `backups/project_<최신>.zip` 을 풀어 `project/` 를 되돌린다 (2-D 참고).
5. **`images/` 복원** — 외부 백업에서 복사한다. **zip 에 없다.**
6. **환경변수 등록** — [ENV_SETUP.md](ENV_SETUP.md) 의 `setx`.
   등록 후 **새 PowerShell 창**을 연다.
7. **로컬 LLM 준비** — `c:\Users\USER\claude\local_llm` 의 모델 파일(GGUF)은 이 저장소에 없다.
   별도로 옮기거나 다시 받아야 한다. 그 뒤 `runtime\serve.ps1`.
8. **검증**
   ```
   python tools/doctor.py                    # 전 항목 OK 인지
   python tools/check_protocol.py            # RESULT: PASS
   python tools/backup_project.py verify     # 무결성
   python tools/secret_scan.py               # 비밀값 없음
   python tools/selftest.py                  # 파이프라인 회귀 (포트를 쓰므로 서버는 꺼두고)
   ```
9. **첫 기동**
   ```
   powershell -ExecutionPolicy Bypass -File start_studio.ps1
   ```

---

## 4. 평상시 예방 (5분)

- 승인 도장을 찍은 날 → `python tools/backup_project.py snapshot`
- 한 달에 한 번 → `images/` 폴더를 외부 매체에 통째로 복사
- 인화 주문 직전 → `python tools/backup_project.py verify`
- 도구·스키마를 고친 뒤 → `python tools/selftest.py` 전체 통과 확인
- 가끔 → `python tools/doctor.py` 로 경고가 늘지 않았는지 확인

가장 흔한 사고는 디스크 고장이 아니라 **"환경변수가 세션 전용이었다"** 와
**"이미지는 백업에 없었다"** 두 가지다. 둘 다 오늘 5분이면 막을 수 있다.
