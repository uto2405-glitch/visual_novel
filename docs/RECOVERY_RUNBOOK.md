# 재해 복구 런북 — 고장났을 때 순서대로

당황해서 순서를 틀리면 살릴 수 있던 것도 날아간다. 증상별로 **무엇을 먼저 할지**만 적었다.

## 0. 어떤 상황이든 첫 두 줄

```
python tools/doctor.py          # 무엇이 깨졌는지 30초 안에 좁힌다 (읽기 전용)
python tools/backup_project.py verify   # 원본이 성한지 (sha256 대조)
```

**아직 아무것도 지우거나 덮어쓰지 마라.** 진단이 먼저다.
복구는 `restore` 하나로 한다 — 손으로 zip 을 푸는 건 마지막 수단이다(§2-C).

---

## 1. 무엇이 백업되고, 무엇이 안 되는가 (가장 중요)

**이미지가 복구되는지 아닌지는 그 스냅샷을 어떻게 떴느냐가 결정한다.**

| 명령 | zip 에 들어가는 것 | 이미지 복구 |
|---|---|---|
| `snapshot` | `project/` 만 (매니페스트·장면 JSON·스토리라인) | ✗ 체크섬만 — 손상은 탐지, 복구는 불가 |
| `snapshot --with-images` | `project/` + **승인 장면이 쓰는 이미지 원본** | ✔ `restore` 로 되돌아온다 |
| `snapshot --with-images --images-scope all` | `project/` + `images/` **전체** | ✔ 후보컷까지 전부 |

`manifest_<시각>.json` 은 어느 경우든 `project/` **와** `images/` 전체의 sha256 을 기록한다
(무결성 검증용 — 체크섬은 복구 수단이 아니다).

> ### ⚠ 기본 `snapshot` 은 이미지를 담지 않는다
> 승인된 컷은 유료 생성물이자 유일본이다 — 같은 프롬프트로도 같은 그림은 나오지 않는다.
> `.gitignore` 가 `images/raw/` 를 제외하므로 **git 도 이미지 백업이 아니다.**
> 그래서 승인 도장을 찍은 날의 표준 명령은 이것이다:
>
> ```
> python tools/backup_project.py snapshot --with-images --dest D:/backup --keep 12
> ```
>
> `--images-scope approved`(기본)는 **APPROVED 장면의 `raw_images`·`selected_image`** 만 담는다.
> 후보컷까지 통째로 지키려면 `--images-scope all`.
> `--dest` 는 zip 과 체크섬 매니페스트를 외장드라이브·클라우드 폴더에 한 벌 더 복사한다
> (같은 디스크가 죽으면 백업도 같이 죽는다). `--keep N` 은 최신 N개만 남긴다.

지금 있는 백업이 이미지를 담고 있는지는 목록에서 바로 보인다:

```
python tools/backup_project.py list
  20260825_030705 — 32개 파일 · zip 509.6KB · 이미지 포함(approved)
```

`이미지 포함` 표시가 없는 줄은 **그 시점의 이미지를 되돌릴 수 없는 백업**이다.

### 자동으로 뜨게 하기

```
python tools/backup_project.py schedule --dry-run     # 등록 명령만 보여준다
```

매일 정해진 시각에 `snapshot + verify` 를 돌리는 PowerShell 스크립트와 `schtasks` 등록 명령을
만들어 준다(등록 자체는 사람이 실행한다). `--with-images --dest D:/backup` 를 함께 주면
예약 백업도 이미지를 담는다.

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

웹 스튜디오는 손상 장면을 건너뛰고 살아남도록 되어 있다. **먼저 미리보기부터.**

```
python tools/backup_project.py restore --dry-run
```

출력은 `동일 N · 덮어씀 N · 새로 생성 N` 과 그 목록이다. 여기서 판단이 갈린다.

- **덮어쓸 목록이 그 장면 하나뿐** → 그대로 실행한다. 같은 파일은 건드리지 않는다.
  ```
  python tools/backup_project.py restore
  ```
  확인 문구 `복원` 을 입력하면 진행한다(스크립트에서는 `--yes`).
  덮어쓰기 전 현재 내용은 `backups/prerestore_<시각>.zip` 에 자동 보관된다 — **복원 자체를 되돌릴 수 있다.**
- **다른 장면까지 덮어쓴다고 나온다** → 스냅샷 이후에 한 작업이 함께 되감긴다는 뜻이다.
  그 한 파일만 살리려면 손으로 꺼낸다:
  ```powershell
  $tmp = "$env:TEMP\vn_restore"
  New-Item -ItemType Directory -Force $tmp | Out-Null
  Expand-Archive -Path "backups\project_20260825_030705.zip" -DestinationPath $tmp -Force
  Copy-Item "$tmp\project\scenes\SCENE-003.json" "project\scenes\SCENE-003.json"
  ```

```
python tools/check_protocol.py --scene SCENE-003     # 확인
```

`restore` 는 **`project/` 와 `images/` 밖의 경로를 절대 건드리지 않고**(zip slip 차단),
스냅샷에 없는 현재 파일도 지우지 않는다. 옛 스냅샷으로 돌아가려면 `--snapshot 20260824_224601`,
외장드라이브의 백업을 쓰려면 `--from D:/backup`.

### D. `project/` 폴더 전체를 날렸다

```
python tools/backup_project.py list                  # 어느 스냅샷으로 갈지 고른다
python tools/backup_project.py restore --dry-run     # 무엇이 새로 생기는지 확인
python tools/backup_project.py restore               # 확인 문구 '복원' 입력
python tools/check_protocol.py
python tools/backup_project.py verify
```

`--with-images` 로 뜬 스냅샷이면 이미지 원본도 같은 명령으로 함께 돌아온다.
`verify` 가 `✗ 누락` 으로 `images/...` 를 잔뜩 뱉는다면 그 스냅샷에 이미지가 없었던 것이다 —
외부 백업에서 `images/` 를 복사한다(§1 · §2-F).

### E. `verify` 가 "변경/손상"을 보고한다

두 경우다.
- **내가 고친 것**(장면 편집·새 이미지 승인) → 정상이다. `snapshot` 을 다시 떠서 기준을 갱신한다.
- **아무것도 안 했는데 바뀜** → 비트로트나 디스크 문제일 수 있다.
  `restore --dry-run` 으로 무엇이 달라졌는지 목록으로 확인하고, 디스크 상태를 점검한다.
  **인화 주문 직전에 반드시 확인할 것.**

### F. 승인된 장면의 이미지 원본이 사라졌다

`doctor` 의 `[프로젝트] 선택 이미지 존재` 항목이 잡아 준다.
1. `--with-images` 스냅샷이 있으면 `restore` 로 끝난다(§2-D). `list` 로 먼저 확인한다.
2. 없으면 외부 백업에서 `images/raw/<SCENE-ID>/` 를 복원한다.
3. 복원할 사본이 정말 없다면, 그 장면은 승인을 되돌리고 다시 만드는 수밖에 없다:
   ```
   python tools/advance_scene.py revise SCENE-00X IMAGE --note "원본 소실"
   ```
   (같은 프롬프트로 다시 생성해도 같은 그림은 나오지 않는다. 그래서 1·2번이 중요하다.)

### G. 토큰이 유출된 것 같다

**순서가 중요하다 — 폐기가 먼저다.**
1. 발급처에서 해당 토큰 **폐기 후 재발급**.
2. `python tools/secret_scan.py` 로 저장소 전체 확인 (실제 값은 출력되지 않는다).
3. `python tools/check_protocol.py` 의 A8 확인.
4. 새 토큰을 `setx` 로 등록 → **[ENV_SETUP.md](ENV_SETUP.md)** 5번.
5. 커밋된 적이 있으면 파일을 고쳐도 이력에 남는다. 이 경우 이력 처리는 되돌릴 수 없으므로
   에이전트가 임의로 하지 않고 사용자가 결정한다.

### H. 백업 폴더가 부풀었다 / `project/scenes_backup_*` 이 보인다

```
python tools/backup_project.py prune --dry-run       # 오래된 스냅샷 정리 계획
python tools/backup_project.py migrate --dry-run     # 옛 사본을 backups/legacy/ 로 이관
```
둘 다 확인 후 `--yes` 로 실행한다. `project/` 안에 남은 옛 사본은 스냅샷마다 함께 담겨
백업을 부풀리고, 장면 폴더를 훑는 도구가 사본을 실제 장면으로 착각할 여지도 만든다.

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
4. **백업을 제자리에 둔다** — 외장드라이브의 `project_*.zip` · `manifest_*.json` 을
   저장소의 `backups/` 로 복사한다. (복사하지 않고 `restore --from D:/backup` 으로 바로 써도 된다.)
5. **`project/` · `images/` 복원**
   ```
   python tools/backup_project.py list
   python tools/backup_project.py restore --dry-run
   python tools/backup_project.py restore
   ```
   `--with-images` 로 뜬 스냅샷이면 이미지도 여기서 함께 돌아온다.
   아니면 `images/` 는 외부 백업에서 따로 복사해야 한다.
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

- 승인 도장을 찍은 날 →
  `python tools/backup_project.py snapshot --with-images --dest D:/backup --keep 12`
- 한 달에 한 번 → 외장 매체의 백업이 실제로 열리는지 확인
  (`python tools/backup_project.py list --from D:/backup`)
- 인화 주문 직전 → `python tools/backup_project.py verify`
- 도구·스키마를 고친 뒤 → `python tools/selftest.py` 전체 통과 확인
- 가끔 → `python tools/doctor.py` 로 경고가 늘지 않았는지 확인

가장 흔한 사고는 디스크 고장이 아니라 **"환경변수가 세션 전용이었다"** 와
**"그 스냅샷에 이미지가 없었다"** 두 가지다. 둘 다 오늘 5분이면 막을 수 있다.
