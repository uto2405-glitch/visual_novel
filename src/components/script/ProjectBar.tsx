/** 대본실 상단 프로젝트 바 + 최근 프로젝트 목록(표지 썸네일). */
import { useEffect, useRef, useState } from "react";
import { useStudio } from "../../store/useStudio";
import { takeFiles } from "../../lib/blob";
import { fmtTime } from "../../lib/format";
import { getProjectThumbBlob } from "../../lib/db";
import { parseEpisode, seriesKey } from "../../lib/episodes";

export function ProjectBar() {
  const hasProject = useStudio((s) => s.project !== null);
  const newProject = useStudio((s) => s.newProject);
  const saveNow = useStudio((s) => s.saveNow);
  const saveAsNew = useStudio((s) => s.saveAsNew);
  const nextEpisode = useStudio((s) => s.nextEpisode);
  const exportProject = useStudio((s) => s.exportProject);
  const importFromFile = useStudio((s) => s.importFromFile);
  const importManyFromFiles = useStudio((s) => s.importManyFromFiles);
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <div className="projectbar">
      <button className="btn" onClick={() => void newProject()}>
        새 프로젝트
      </button>
      <button
        className="btn btn-primary"
        disabled={!hasProject}
        onClick={() => void saveNow()}
        title="story + 배우 사진 + 생성 이미지 + 컷 상태 + 시사 커서를 한 묶음으로 저장합니다"
      >
        오늘 촬영분 넣기
      </button>
      <button
        className="btn"
        disabled={!hasProject}
        title="지금 작품의 화풍·감독 노트와 배우(캐스팅 사진째)를 물려받은 다음 화를 만듭니다 — 연재를 이어 쓸 때"
        onClick={() => void nextEpisode()}
      >
        ▶ 다음 화 만들기
      </button>
      <button className="btn" disabled={!hasProject} onClick={() => void saveAsNew()}>
        다른 이름으로 저장
      </button>
      <button className="btn" onClick={() => fileRef.current?.click()}>
        내 기기에서 불러오기
      </button>
      <button className="btn" disabled={!hasProject} onClick={() => void exportProject()}>
        내 기기로 내보내기
      </button>
      <input
        ref={fileRef}
        type="file"
        // 여러 개 — 「🎞 모두 내보내기」로 꺼낸 스무 편을 한 번에 되돌릴 수 있어야 이사가 된다
        multiple
        accept=".zip,.json,application/zip,application/x-zip-compressed,application/json"
        style={{ display: "none" }}
        onChange={(e) => {
          const files = takeFiles(e.currentTarget); // FileList 즉시 복사 → 그 다음 리셋
          if (files.length > 1) void importManyFromFiles(files);
          else if (files[0]) void importFromFile(files[0]);
        }}
      />
      <RecentList />
    </div>
  );
}

function RecentList() {
  const list = useStudio((s) => s.projectList);
  const current = useStudio((s) => s.project?.id);
  const exportAllProjects = useStudio((s) => s.exportAllProjects);
  const exportOmnibus = useStudio((s) => s.exportOmnibus);
  // 지금 작품이 속한 연재가 몇 편인가 — 「우산 3화」의 앞머리가 같은 화들(찍은 컷이 있는 것만)
  const curTitle = useStudio((s) => s.project?.title);
  const here = curTitle ? parseEpisode(curTitle) : null;
  const seriesCount = here
    ? list.filter((e) => {
        const p = parseEpisode(e.title);
        return p && p.key === here.key && e.okCount > 0;
      }).length
    : 0;
  const openProject = useStudio((s) => s.openProject);
  const deleteProject = useStudio((s) => s.deleteProject);
  const [open, setOpen] = useState(false);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});

  // 열릴 때 표지 썸네일을 IndexedDB에서 로드 — 필름 선반처럼
  useEffect(() => {
    if (!open) return;
    let alive = true;
    const urls: string[] = [];
    void (async () => {
      const next: Record<string, string> = {};
      for (const e of list.slice(0, 8)) {
        try {
          const blob = await getProjectThumbBlob(e.id);
          if (!alive) break;
          if (blob) {
            const u = URL.createObjectURL(blob);
            urls.push(u);
            next[e.id] = u;
          }
        } catch {
          /* 썸네일은 장식 — 실패해도 목록은 산다 */
        }
      }
      if (alive) setThumbs(next);
    })();
    return () => {
      alive = false;
      for (const u of urls) URL.revokeObjectURL(u);
      setThumbs({});
    };
    // eslint가 권하는 대로 open/list를 딥워치하면 편집마다 IDB를 두드린다 — 열림 시 1회면 충분
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (list.length === 0) return null;
  return (
    <div className="recent">
      <button className="btn btn-ghost" onClick={() => setOpen((v) => !v)}>
        최근 프로젝트 {open ? "▾" : "▸"}
      </button>
      {open && list.length > 1 && (
        <button
          className="btn btn-ghost btn-small"
          title="이 브라우저의 모든 작품을 각자의 필름캔(ZIP)으로 내보냅니다 — 새 기기로 옮길 때"
          onClick={() => void exportAllProjects()}
        >
          🎞 모두 내보내기 ({list.length}편)
        </button>
      )}
      {/* 합본 — 연재의 끝에 오는 일. 같은 앞머리의 화가 둘 이상일 때만 문을 낸다 */}
      {open && seriesCount > 1 && (
        <button
          className="btn btn-ghost btn-small"
          title="이 연재의 화들을 한 권으로 조판해 PDF 한 파일로 냅니다 — 표지·목차·등장인물 장은 한 번만, 쪽 번호는 이어집니다"
          onClick={() => void exportOmnibus()}
        >
          📖 합본 ({seriesCount}편)
        </button>
      )}
      {/* 연재 전체의 진도 — 편마다 막대는 있었지만 «연재 전체가 어디까지»는 아무 데도 없었다.
          20편을 쓰는 사람의 첫 질문이 그것이다. 목록이 이미 들고 있는 수를 더하기만 하면 된다. */}
      {open && list.length > 1 && (
        <div className="fine plist-total">
          {(() => {
            const cuts = list.reduce((n, e) => n + (e.sceneCount || 0), 0);
            const ok = list.reduce((n, e) => n + (e.okCount || 0), 0);
            const done = list.filter((e) => e.sceneCount > 0 && e.okCount >= e.sceneCount).length;
            const pct = cuts > 0 ? Math.round((ok / cuts) * 100) : 0;
            /* 제작비도 더한다 — 이 앱에서 가장 조심할 값이고, 편마다 흩어져 있으면 총액을 모른다.
               크레딧 사본이 없는 «옛 목록»의 편은 합계에서 빼고 그 수를 밝힌다(모르는 것을 0으로
               세면 총액이 거짓이 된다). */
            const known = list.filter((e) => typeof e.coinsSpent === "number");
            const coins = known.reduce((n, e) => n + (e.coinsSpent ?? 0), 0);
            const unknown = list.length - known.length;
            const money =
              coins > 0
                ? ` · 제작비 ${coins.toLocaleString("ko-KR")}코인${unknown > 0 ? ` (${unknown}편은 아직 모름)` : ""}`
                : "";
            /* 한 연재만 있으면 «연재 전체», 여러 작품이 섞여 있으면 «저장된» — 합계는 언제나
               이 브라우저의 모든 편이므로 이름이 그 사실과 어긋나지 않아야 한다 */
            const stems = new Set(list.map((e) => seriesKey(e.title)));
            const scope = stems.size === 1 ? "연재 전체" : "저장된";
            return `${scope} ${list.length}편 · ${cuts}컷 중 ${ok}컷 OK (${pct}%) · 다 찍은 편 ${done}${money}`;
          })()}
        </div>
      )}
      {open && (
        <div className="plist">
          {list.map((e) => (
            <div key={e.id} className={`plist-item ${e.id === current ? "active" : ""}`}>
              <button className="plist-open" onClick={() => void openProject(e.id)}>
                <span className="plist-thumb">
                  {thumbs[e.id] ? <img src={thumbs[e.id]} alt="" /> : <span>🎬</span>}
                </span>
                <span className="plist-text">
                  <span className="plist-title">
                    {e.title}
                    {/* 연재가 쌓이면 «이 화는 필름캔이 있나»가 목록에서 보여야 한다 */}
                    {e.lastExportAt ? (
                      <span className="plist-can" title={`필름캔 ${fmtTime(e.lastExportAt)}`}>
                        🎞
                      </span>
                    ) : null}
                  </span>
                  <span className="plist-meta">
                    장면 {e.sceneCount} · OK {e.okCount} · {fmtTime(e.updatedAt)}
                  </span>
                  {/* 진행 막대 — 여러 화를 오갈 때 «어디까지 찍었나»를 한눈에 */}
                  {e.sceneCount > 0 && (
                    <span
                      className="plist-bar"
                      title={`${e.okCount}/${e.sceneCount}컷 촬영됨`}
                      aria-hidden="true"
                    >
                      <span
                        className="plist-bar-fill"
                        style={{ width: `${Math.min(100, Math.round((e.okCount / e.sceneCount) * 100))}%` }}
                      />
                    </span>
                  )}
                </span>
              </button>
              <button
                className="btn btn-ghost btn-small"
                title="이 브라우저에서 지우기"
                onClick={() => void deleteProject(e.id)}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
