/** 캐스팅 — 배우 사진 업로드(ref 파일명 매칭)와 얼굴/얼굴 없음 표시. */
import { useEffect, useRef, useState } from "react";
import { useStudio } from "../../store/useStudio";
import { takeFiles } from "../../lib/blob";
import { useCharPhoto, useProject } from "../hooks";
import { chapterRanges } from "../../lib/chapters";
import { useObjectUrl } from "../../lib/hooks";

export function Casting() {
  const project = useProject();
  const uploadCharFiles = useStudio((s) => s.uploadCharFiles);
  const fileRef = useRef<HTMLInputElement>(null);
  const chars = project.story.characters;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>캐스팅</h2>
        <div className="panel-actions">
          <TroupeButton />
          <button className="btn" onClick={() => fileRef.current?.click()}>
            배우 사진 올리기 (JPG)
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            multiple
            style={{ display: "none" }}
            onChange={(e) => {
              const files = takeFiles(e.currentTarget); // 참조 소실 방지: 복사 후 리셋
              if (files.length) void uploadCharFiles(files);
            }}
          />
        </div>
      </div>
      {chars.length === 0 ? (
        <p className="fine">
          아직 배우가 없습니다. <b>배우 사진 올리기</b>를 누르면 사진으로 새 배우를 바로
          캐스팅할 수 있어요. (「고급」의 story.json으로 넣어도 됩니다)
        </p>
      ) : (
        <div className="cast">
          {chars.map((c) => (
            <CastRow key={c.id} charId={c.id} />
          ))}
        </div>
      )}
      <p className="fine">
        캐스팅 사진은 같은 얼굴을 지키는 기준입니다 — 잘 나온 정면 사진 한 장이면 충분해요.
        파일명이 <code>ref</code>와 같으면 자동으로 걸리고, 달라도(폰 갤러리 사진 등) 각 배우의
        「사진 올리기」로 직접 걸 수 있습니다.
      </p>
    </section>
  );
}

function CastRow({ charId }: { charId: string }) {
  const removeCharImage = useStudio((s) => s.removeCharImage);
  const uploadCharPhotoFor = useStudio((s) => s.uploadCharPhotoFor);
  const updateCharacter = useStudio((s) => s.updateCharacter);
  const removeCharacter = useStudio((s) => s.removeCharacter);
  const saveToTroupe = useStudio((s) => s.saveToTroupe);
  const promptText = useStudio((s) => s.promptText);
  const { char: c, url } = useCharPhoto(charId);
  const project = useProject();
  const setDeskChapter = useStudio((st) => st.setDeskChapter);
  const fileRef = useRef<HTMLInputElement>(null);
  if (!c) return null;
  const ref = c.ref;

  /**
   * 이 배우가 나온 장 — 연재가 길어지면 「하나가 언제 나왔더라」를 대본을 훑어 찾게 된다.
   * 장이 둘 이상일 때만 낸다(한 장짜리 작품에는 «1장» 한 줄이 군더더기다).
   */
  const chapters = chapterRanges(project.story.scenes);
  const cuts = project.story.scenes.filter((sc) => sc.chars?.includes(charId));
  const inChapters = chapters.filter((ch) => cuts.some((sc) => ch.ids.includes(sc.id)));

  const editProfile = async () => {
    const text = await promptText({
      title: `배우 「${c.name}」 프로필`,
      body: "첫 줄 = 이름, 둘째 줄 = 외모 메모(영어, 프롬프트에 실림 — 비워도 됩니다).",
      initial: c.look ? `${c.name}\n${c.look}` : c.name,
      multiline: true,
      okLabel: "반영",
    });
    if (text === null) return;
    const [nameLine, ...rest] = text.split("\n");
    const name = nameLine.trim();
    if (!name) return;
    updateCharacter(charId, { name, look: rest.join(" ").trim() || undefined });
  };
  return (
    <div className="cast-row">
      <div className="cast-photo">
        {url ? <img src={url} alt={c.name} /> : <span className="cast-nophoto">얼굴 없음</span>}
      </div>
      <div className="cast-info">
        <div className="cast-name">
          {c.name} <span className="chip">{c.id}</span>
          {url ? (
            <span className="badge badge-face">얼굴</span>
          ) : (
            <span className="badge badge-noface">얼굴 없음</span>
          )}
        </div>
        <div className="cast-meta">
          {c.look ? <>{c.look} · </> : null}
          <code>{ref ?? "(ref 없음)"}</code>
        </div>
        {/* 어느 컷에도 켜지지 않은 배우 — 사진을 걸어도 그 얼굴은 «어떤 컷에도» 실리지 않는다.
            예전에는 장이 둘 이상일 때만 이 줄을 냈다(사용자: 사진은 걸었는데 얼굴이 전송이 안 된다). */}
        {cuts.length === 0 && (
          <div className="cast-chapters fine">
            아직 어느 컷에도 등장 배우로 켜져 있지 않아요 — 컷 카드의 배우 칩을 켜야 이 얼굴이 찍힙니다.
          </div>
        )}
        {chapters.length >= 2 && cuts.length > 0 && (
          <div className="cast-chapters fine">
            {cuts.length === 0 ? (
              "아직 어느 컷에도 등장 배우로 켜져 있지 않아요"
            ) : (
              <>
                출연 —{" "}
                {inChapters.slice(0, 4).map((ch, i) => (
                  <span key={ch.firstId}>
                    {i > 0 ? " · " : ""}
                    {/* 이름을 누르면 정리대가 그 장만 보여준다 — «언제 나왔더라» 다음은 «그 장을 보자»다 */}
                    <button
                      type="button"
                      className="linkish"
                      title={`정리대를 「${ch.title}」만 보이게 맞춥니다`}
                      onClick={() => setDeskChapter(ch.firstId)}
                    >
                      {ch.title}
                    </button>
                  </span>
                ))}
                {inChapters.length > 4 ? ` 외 ${inChapters.length - 4}장` : ""} ({cuts.length}컷)
              </>
            )}
          </div>
        )}
      </div>
      <button
        className="btn btn-small"
        title="파일명과 상관없이 이 배우에게 캐스팅 사진을 겁니다"
        onClick={() => fileRef.current?.click()}
      >
        {url ? "사진 바꾸기" : "사진 올리기"}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        style={{ display: "none" }}
        onChange={(e) => {
          const files = takeFiles(e.currentTarget); // FileList 즉시 복사 → 그 다음 리셋
          if (files[0]) void uploadCharPhotoFor(charId, files[0]);
        }}
      />
      {url && ref && (
        <button className="btn btn-ghost btn-small" onClick={() => removeCharImage(ref)}>
          사진 빼기
        </button>
      )}
      {url && (
        <button
          className="btn btn-ghost btn-small"
          title="이 배우를 전속 배우단에 올립니다 — 다음 작품에 사진째로 데려갈 수 있어요"
          onClick={() => void saveToTroupe(charId)}
        >
          ⭐ 배우단
        </button>
      )}
      <button
        className="btn btn-ghost btn-small"
        title="이름·외모 메모 수정"
        onClick={() => void editProfile()}
      >
        ✎
      </button>
      {url && <CastCropChips charId={charId} crop={c.castCrop} />}
      <button
        className="btn btn-ghost btn-small btn-danger-ghost"
        title="배우 하차 (확인창) — 되돌리기(↩)로 복귀 가능"
        onClick={() => void removeCharacter(charId)}
      >
        하차
      </button>
    </div>
  );
}

/** 전속 배우단 — 프로젝트를 넘어 사는 배우 선반. 열 때 목록을 읽는다. */
function TroupeButton() {
  const troupe = useStudio((s) => s.troupe);
  const loadTroupe = useStudio((s) => s.loadTroupe);
  const castFromTroupe = useStudio((s) => s.castFromTroupe);
  const removeFromTroupe = useStudio((s) => s.removeFromTroupe);
  const replaceTroupePhoto = useStudio((s) => s.replaceTroupePhoto);
  const editTroupeProfile = useStudio((s) => s.editTroupeProfile);
  const [open, setOpen] = useState(false);
  const works = useStudio((s) => s.troupeWorks);
  // 「그 편으로 가기」 — 지금 열린 편은 누를 것이 없으므로 id를 함께 넘긴다
  const project = useStudio((s) => s.project);
  const openProject = useStudio((s) => s.openProject);

  const loadTroupeWorks = useStudio((s) => s.loadTroupeWorks);
  useEffect(() => {
    if (open) {
      void loadTroupe();
      // 「어디에 나왔나」는 저장된 작품 전체를 훑어야 안다 — 선반을 열 때, 그리고 편이 바뀔 때.
      // 선반을 열어둔 채 다음 화를 만들면 출연 목록이 낡은 채 남았다(실측) — 그때 다시 센다.
      void loadTroupeWorks();
    }
    // 대본이 바뀌어도(반영·컷 추가) 다시 센다 — 원시값이라 렌더마다 도는 일은 없다
  }, [
    open,
    project?.id,
    project?.story.scenes.length,
    project?.story.characters.length,
    loadTroupe,
    loadTroupeWorks,
  ]);

  return (
    <div className="troupe-wrap">
      <button
        className={`btn ${open ? "btn-toggled" : ""}`}
        title="여러 작품에 걸쳐 같은 배우를 쓰는 전속 배우단 — 사진째로 데려옵니다"
        onClick={() => setOpen((v) => !v)}
      >
        ⭐ 전속 배우단{troupe.length > 0 ? ` (${troupe.length})` : ""}
      </button>
      {open && (
        <div className="troupe">
          {troupe.length === 0 ? (
            <p className="fine">
              아직 배우단이 비어 있습니다. 배우 카드의 <b>⭐ 배우단</b>을 누르면 그 배우가
              여기에 올라오고, 다음 작품에서 사진째로 데려올 수 있어요.
            </p>
          ) : (
            <div className="troupe-list">
              {troupe.map((a) => (
                <TroupeCard
                  key={a.id}
                  actor={a}
                  works={works[a.name] ?? []}
                  openId={project?.id}
                  onCast={() => void castFromTroupe(a.id)}
                  onOpen={(pid) => void openProject(pid)}
                  onRemove={() => void removeFromTroupe(a.id)}
                  onPhoto={(f) => void replaceTroupePhoto(a.id, f)}
                  onEdit={() => void editTroupeProfile(a.id)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TroupeCard({
  actor,
  works,
  openId,
  onCast,
  onOpen,
  onRemove,
  onPhoto,
  onEdit,
}: {
  actor: { id: string; name: string; look?: string; photo: Blob; appearances: number };
  works: { id: string; title: string; chapters: string[]; cuts: number }[];
  /** 지금 열려 있는 작품 id — 그 편은 누를 것이 없다 */
  openId?: string;
  onCast: () => void;
  onOpen: (projectId: string) => void;
  onRemove: () => void;
  onPhoto: (file: File) => void;
  onEdit: () => void;
}) {
  const url = useObjectUrl(actor.photo);
  const fileRef = useRef<HTMLInputElement>(null);
  const [showAll, setShowAll] = useState(false);
  return (
    <div className="troupe-card">
      <div className="troupe-photo">{url && <img src={url} alt={actor.name} />}</div>
      <div className="troupe-info">
        <div className="cast-name">{actor.name}</div>
        <div className="fine">
          {/* 두 숫자는 뜻이 다르다 — «컷에 나온 편수»(작품을 훑어 센 값, 아래 목록과 같은 근거)와
              «데려온 편수»(배우단에서 캐스팅한 횟수). 다를 때는 둘 다, 각자 이름을 달고 보여준다.
              하나만 남기면 «데려왔지만 아직 안 쓴 화»가 사라지고, 이름을 안 달면 어느 쪽도 못 믿는다. */}
          {works.length > 0
            ? `${works.length}편에 나옴`
            : `데려온 ${actor.appearances}편`}
          {works.length > 0 && actor.appearances > works.length
            ? ` · 데려온 ${actor.appearances}편`
            : ""}
          {actor.look ? ` · ${actor.look.slice(0, 24)}` : ""}
        </div>
        {/* 「N편 출연」 숫자만으로는 «어느 작품 몇 장»을 알 수 없다 — 연재가 길어지면 그게 궁금해진다.
            그리고 알고 나면 «거기로 가고» 싶어진다 — 20편에서 목록을 다시 뒤지게 하지 않는다.
            지금 열려 있는 편은 누를 것이 없으므로 «(지금 이 편)»으로 표시만 한다. */}
        {works.length > 0 && (
          <div className="fine troupe-works">
            {works.slice(0, showAll ? works.length : 2).map((w) => (
              <div key={w.id || w.title}>
                {w.id === openId ? (
                  <span title={`${w.title} — ${w.cuts}컷 (지금 열려 있는 편)`}>「{w.title}」</span>
                ) : (
                  <button
                    type="button"
                    className="troupe-open"
                    title={`「${w.title}」을 엽니다 — ${w.cuts}컷`}
                    onClick={() => onOpen(w.id)}
                  >
                    「{w.title}」
                  </button>
                )}
                {w.chapters.length > 0 ? ` ${w.chapters.slice(0, 3).join("·")}` : ""}
                {w.chapters.length > 3 ? "…" : ""} <span className="troupe-cuts">{w.cuts}컷</span>
                {w.id === openId ? <span className="troupe-here"> · 지금 이 편</span> : null}
              </div>
            ))}
            {/* 여덟 화를 넘기면 「외 6편」에 여섯 편이 묻힌다 — 그 여섯도 눌러서 갈 수 있어야 한다.
                기본은 접힌 채로 둔다(배우가 여럿이면 선반이 길어진다). */}
            {works.length > 2 && (
              <button type="button" className="troupe-open" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "접기 ▴" : `외 ${works.length - 2}편 ▾`}
              </button>
            )}
          </div>
        )}
      </div>
      <button className="btn btn-small" onClick={onCast} title="이 작품에 데려옵니다">
        데려오기
      </button>
      <button
        className="btn btn-small btn-ghost"
        title="더 잘 나온 사진으로 이 배우의 얼굴을 갈아끼웁니다"
        onClick={() => fileRef.current?.click()}
      >
        📷
      </button>
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        style={{ display: "none" }}
        onChange={(e) => {
          const files = takeFiles(e.currentTarget);
          if (files[0]) onPhoto(files[0]);
        }}
      />
      <button className="btn btn-small btn-ghost" title="이름·외모 메모 고치기" onClick={onEdit}>
        ✎
      </button>
      <button className="btn btn-small btn-ghost" onClick={onRemove} title="배우단에서 빼기">
        ✕
      </button>
    </div>
  );
}

/**
 * 인쇄본 「등장인물」 장의 사진 크롭 위치 — 감독이 고른다.
 *
 * 비율로 자동 판정해봤지만 인물이 세로 가운데 있는 사진에서 얼굴이 잘렸다(실측).
 * 얼굴 검출 없이 항상 옳은 비율은 없으니, 얼굴이 있는 쪽을 직접 누르게 한다.
 */
function CastCropChips({
  charId,
  crop,
}: {
  charId: string;
  crop?: { x?: "left" | "center" | "right"; y?: "top" | "center" | "bottom" };
}) {
  const updateCharacter = useStudio((s) => s.updateCharacter);
  const set = (patch: { x?: "left" | "center" | "right"; y?: "top" | "center" | "bottom" }) =>
    updateCharacter(charId, { castCrop: { ...crop, ...patch } });
  return (
    <span className="castcrop" title="인쇄본 등장인물 장에서 얼굴이 있는 쪽을 남깁니다">
      {(
        [
          ["y", "top", "위"],
          ["y", "center", "중"],
          ["y", "bottom", "아래"],
        ] as const
      ).map(([, v, label]) => (
        <button
          key={v}
          type="button"
          className={`chip chipbtn ${(crop?.y ?? "") === v ? "chip-on" : ""}`}
          onClick={() => set({ y: v })}
        >
          {label}
        </button>
      ))}
      {(crop?.x || crop?.y) && (
        <button
          type="button"
          className="chip chipbtn"
          title="기본 크롭으로 되돌리기"
          onClick={() => updateCharacter(charId, { castCrop: null })}
        >
          ↺
        </button>
      )}
    </span>
  );
}
