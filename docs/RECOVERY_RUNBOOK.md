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

> ### ⚠ 개인 대화 기록은 백업에 담기지 않는다 (기본값)
> `chatlog.json` · `talk_*.json` · `*.archive.jsonl` · `memory_*.json` 은 **인물과 나눈 사적
> 대화**다(→ [SCHEMA.md](SCHEMA.md) §3.1). 이 넷은 zip 에도, 함께 복사되는 체크섬 매니페스트
> 에도 들어가지 않는다 — 바로 아래의 표준 명령이 `--dest D:/backup` 을 권하고, 그 폴더가
> **클라우드 동기화 폴더**면 백업 한 줄이 사적 대화를 제3자 서버에 올리기 때문이다.
>
> ```
> python tools/backup_project.py snapshot --include-private     # 정말 담아야 할 때만
> ```
>
> `--include-private` 와 `--dest` 를 함께 주면 확인(`포함`)을 묻는다. 예약 실행처럼 확인이
> 불가능한 자리에서는 **사적 기록만 빼고 백업은 계속한다** — 백업 자체를 멈추면 작품까지
> 안 지켜진다. 그래서 **대화 기록은 이 도구의 복구 대상이 아니다**: 잃고 싶지 않다면
> `project/story/` 를 손으로 따로 복사해 두거나 `--include-private` 로 뜬 스냅샷을 쓴다.
> 빠졌다고 `verify` 가 이상을 보고하지는 않는다(대상이 아니라고 한 줄로 알린다).

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

> ### 같은 내용이면 다시 굽지 않는다
> `snapshot` 은 뜨기 전에 `project/`·`images/` 의 sha256 을 **최신 매니페스트와 대조**한다.
> 하나도 바뀌지 않았으면 zip 을 새로 굽지 않고 **이미 있는 그 스냅샷을 이름으로 안내**한다
> (`백업 생략 — 마지막 스냅샷 이후 바뀐 파일이 없습니다. [스탬프]`). `--dest` 사본과 `--keep`
> 정리는 그 회차에도 그대로 실행된다 — 외부 폴더에 한 벌 두는 것은 "오늘 새로 구웠는가" 와
> 다른 문제이기 때문이다. 같은 내용을 굳이 한 벌 더 원하면 `--force`.
>
> 이 대조가 없던 시절에는 아무것도 바뀌지 않은 날의 두 번째 실행이 **바이트 단위로 같은
> 112.9MB zip** 을 한 벌 더 만들었다(실측: `project_20260915_075622.zip` 과 `082157.zip`
> 의 sha256 이 `3d361f37…` 로 동일). 백업이 둘이어도 복구력은 하나치인데 용량만 두 배다.
>
> 다만 **담는 것이 다르면 생략하지 않는다** — 어제 뜬 가벼운 스냅샷(`project/` 만) 때문에
> 오늘의 `--with-images` 가 생략되면, 그림을 되돌릴 수 있는 백업이 하나도 없는 상태가
> 조용히 유지된다.

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

`verify` 가 복원 직후 `✗ 누락` 을 뱉는다면 **먼저 무엇이 누락인지 본다.**

- `images/raw/SCENE-0NN/_gen_meta.json` 만 누락(장면 수만큼) → **2026-09-15 이전에 뜬
  옛 스냅샷이다.** 그때는 매니페스트가 `images/` 를 통째로 훑어 생성 기록까지 적는데
  `approved` 범위의 zip 은 컷 파일만 담아서, 되살린 트리가 항상 장면 수만큼 모자랐다
  (실측: 매니페스트 112 · zip 100 · 차이 12 = 장면 12개). **복원된 앨범은 멀쩡하다** —
  `check_protocol` 은 PASS 고 감상본·인화도 정상이다. 그 zip 에 애초에 없는 파일이라
  `restore --snapshot <같은 스탬프>` 를 다시 해도 소용없다(그 안내는 무한 루프였다).
  지금 코드는 `_approved_images` 가 컷 폴더의 `_gen_meta.json` 까지 담으므로 **새로 뜬
  스냅샷에서는 이 증상이 나오지 않는다**(`snapshot` → `restore` → `verify` 가 126/126).
  옛 스냅샷을 계속 쓸 거면 한 번 `snapshot` 을 다시 떠서 기준을 갱신한다.
- 컷 파일(`.png`) 자체가 누락 → 그때가 그 스냅샷에 이미지가 없었던 경우다.
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
둘 다 확인 후 `--yes` 로 실행한다.

`prune` 의 상한은 **둘**이다. `--keep`(기본 12)은 전체 스냅샷 수, `--keep-images`(기본 3)는
그중 **이미지 원본을 담은 스냅샷** 수다. 하나로 세던 시절의 12 는 "23KB zip 열둘" 기준이라,
같은 값이 이미지 스냅샷(실측 118.4MB)에 적용되면 `backups/` 가 1.4GB 로 자란다.
어떤 상한을 줘도 **가장 최신 스냅샷**과 **이미지가 든 가장 최신 스냅샷**은 지우지 않는다. `project/` 안에 남은 옛 사본은 스냅샷마다 함께 담겨
백업을 부풀리고, 장면 폴더를 훑는 도구가 사본을 실제 장면으로 착각할 여지도 만든다.

### I. `이미 생성 중입니다` 만 나오고 이미지 생성이 안 된다

아무것도 굽고 있지 않은데 이 말이 나오면, 생성 중에 프로세스가 비정상 종료해
`logs/gen_locks/<SCENE-ID>.lock` 이 남은 것이다(웹·CLI 이중 과금을 막는 선점 표시).

1. **다른 창에서 정말 굽고 있는지 먼저 본다** — 스튜디오 탭, CLI 터미널. 거부 문구에 찍힌
   `pid`·시작 시각이 어느 쪽인지 알려 준다. 굽고 있으면 그냥 기다린다(끝나면 자동으로 풀린다).
2. 아니면 **20분 기다린다.** 좌초 잠금은 다음 시도가 알아서 회수한다(`gen_jobs.STALE_SEC`).
3. 그것도 싫으면 그 `.lock` 파일을 지운다 — **지워서 잃는 것은 없다.**
   ```powershell
   Remove-Item logs\gen_locks\SCENE-00X.lock
   ```
   단, **정말 생성 중인 장면의 잠금을 지우면 같은 장면을 두 번 굽는 과금이 열린다.** 1번을 먼저 한다.

이미 만들어진 결과가 있다면 재생성이 아니라 **무과금 재수령**으로 받는다:
`python tools/makefun_client.py SCENE-00X --refetch` (→ [SCHEMA.md](SCHEMA.md) §2.6 · §3.5)

**업스케일(`--upscale`)이 실패했을 때는 `--refetch` 가 아니다.** 그 작업 id 는 다른
엔드포인트의 것이라 `makefun_tasks` 에 들어가지 않는다. 대신
`images/raw/<SCENE-ID>/_gen_meta.json` 에서 `kind: "upscale"` 항목을 찾아
**`result_url`** 이 있으면 그 주소로 결과를 직접 받는다 — **다시 결제하지 않는다.**
(→ [SCHEMA.md](SCHEMA.md) §3.2 · [PRINT_ORDER_GUIDE.md](PRINT_ORDER_GUIDE.md) §1)

---

## 3. PC 교체 · 완전 재설치 순서

순서를 지키면 한 번에 끝난다.

1. **Python 3.9+ 설치** — 설치 시 "Add to PATH" 체크.
   ```
   python --version
   ```
2. **가상환경 + Pillow 설치** (스튜디오 실행 스크립트가 `.venv` 를 먼저 찾는다.)
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install Pillow
   ```
   없어도 도구는 돌지만 **결과물이 쓸 수 없게 커진다** — 실측: 같은 감상본이
   Pillow 있으면 2.90MB, 없으면 21.22MB(7.3배)로 나오고 내보내기 도구 스스로
   "15MB 초과 — 폰 전송이 어려울 수 있음" 이라고 경고한다. 인화 마스터는 Pillow 없이는
   아예 못 만든다. 남에게 건넬 파일을 만들 거면 필수로 취급하라.
3. **저장소 복원** — 코드·문서·템플릿. **git 에서만 온다.**

   > `backups/project_*.zip` 에는 **`project/` 와 `images/` 만** 들어 있다(`_zip_payload`).
   > `tools/` 는 한 줄도 없다 — 백업 사본으로는 도구를 되살릴 수 없다.
   > 그러니 **원격에 push 가 돼 있어야 한다**: `git rev-list --count @{u}..HEAD` 가 0 이 아니면
   > 그만큼의 코드가 이 PC 에만 있다. 지금 미는 것이 이 문서의 어떤 복구 절차보다 싸다.
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
                                             # (이미지를 아직 안 되돌렸다면 A3 FAIL 이 정상이다 —
                                             #  --with-images 스냅샷이 없으면 여기서 앨범은 돌아오지 않는다.
                                             #  외부 백업에서 images/ 를 직접 복사하거나,
                                             #  장면을 되돌려 다시 그린다: advance_scene revise <ID> IMAGE
                                             #  → comfyui_client <ID> --n 2, 무료)
   python tools/backup_project.py verify     # 무결성
   python tools/secret_scan.py               # 비밀값 없음
   python tools/selftest.py                  # 파이프라인 회귀 (빈 포트를 알아서 잡는다 — 서버를 끄지 않아도 된다)
   ```
9. **첫 기동**
   ```
   powershell -ExecutionPolicy Bypass -File start_studio.ps1
   ```

---

## 4. 평상시 예방 (5분)

- 승인 도장을 찍은 날 →
  `python tools/backup_project.py snapshot --with-images --dest D:/backup --keep 12`
- **코드를 고친 날 → `git push`**(백업 zip 에는 `tools/` 가 없다 · §3-3).
  `git rev-list --count @{u}..HEAD` 가 이 PC 에만 있는 커밋 수다.
- 한 달에 한 번 → 외장 매체의 백업이 실제로 열리는지 확인
  (`python tools/backup_project.py list --from D:/backup`)
- 인화 주문 직전 → `python tools/backup_project.py verify`
- 도구·스키마를 고친 뒤 → `python tools/selftest.py` 전체 통과 확인
- 가끔 → `python tools/doctor.py` 로 경고가 늘지 않았는지 확인

가장 흔한 사고는 디스크 고장이 아니라 **"환경변수가 세션 전용이었다"** ·
**"그 스냅샷에 이미지가 없었다"** · **"코드를 한 번도 push 하지 않았다"** 세 가지다.
셋 다 오늘 5분이면 막을 수 있다.
