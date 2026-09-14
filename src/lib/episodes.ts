/**
 * 화(episode) 이름 — 한 곳에서만 읽는다.
 *
 * 「역의 우산 3화」처럼 «앞머리 + 숫자 + 표기»가 이 앱의 연재 표기다(「다음 화 만들기」가 그렇게 짓는다).
 * 그 규칙을 두 군데에 베껴 두면 «만들 때의 4화»와 «이어 볼 때의 4화»가 언젠가 어긋난다.
 *
 * 감독은 앱이 지어 준 이름만 쓰지 않는다. 실측(v0.97)에서 이렇게 나왔다:
 *   「우산 01화」→「우산 2화」(자릿수를 잃었다) · 「비 오는 정류장 1편」→「… 1편 2화」(번호가 두 겹)
 *   「하늘 3회」→「하늘 3회 2화」 · 「밤의 서점 3」→「밤의 서점 3 2화」 · 「모래성 (상)」→「… (상) 2화」
 * 그래서 숫자 표기 다섯(화·편·회·장·부)과 자릿수(01→02), 괄호 안 상·중·하, 표기 없는 끝 숫자까지 읽는다.
 *
 * 일부러 읽지 않는 것:
 *  - 괄호 없는 「상·중·하」 — 「최우수상」처럼 그 글자로 끝나는 제목을 화로 오해한다.
 *  - 네 자리 이상의 표기 없는 끝 숫자 — 「소년 1994」는 연도이지 화가 아니다.
 *  - 「Ep.3」·「#3」 같은 표기 — 이 앱이 지어 주지 않는 이름이고, 실제로 쓰는 감독을 아직 보지 못했다.
 */

export interface EpisodeName {
  /** 화 번호 앞의 이름 — 「역의 우산 」(뒤 공백을 포함할 수 있다) */
  stem: string;
  num: number;
  /** 번호 뒤 표기 — 「화」·「편」·「회」·「장」·「부」, 괄호 상·중·하는 「상중하」, 표기가 없으면 빈 문자열 */
  marker: string;
  /** 같은 연재를 묶는 열쇠 — 앞머리와 표기가 둘 다 같아야 같은 연재다(「우산 1화」와 「우산 2편」은 남이다) */
  key: string;
  /** 같은 표기법으로 번호를 다시 쓴다 — 「01화」의 다음은 「02화」. 쓸 수 없으면 빈 문자열(「(하)」 다음은 규칙이 없다) */
  format(num: number): string;
}

/** 괄호 안의 상·중·하 — 두 편(상·하)이든 세 편(상·중·하)이든 순서는 이 순서다 */
const WORDS = ["상", "중", "하"];
/** 상·중·하를 감쌀 수 있는 괄호들 — 괄호가 없으면 화 표기로 보지 않는다 */
const BRACKETS: [string, string][] = [
  ["(", ")"],
  ["（", "）"],
  ["[", "]"],
  ["〈", "〉"],
  ["<", ">"],
];

function make(stem: string, num: number, marker: string, format: (n: number) => string): EpisodeName {
  return { stem, num, marker, key: `${stem.trim()}|${marker}`, format };
}

/** 「역의 우산 3화」 → { stem: "역의 우산 ", num: 3, marker: "화" }. 화 표기가 없으면 null. */
export function parseEpisode(title: string): EpisodeName | null {
  const t = title.trim();

  // (1) 숫자 + 표기 — 「3화」·「01화」·「1편」·「3회」. 자릿수를 기억해 「01화」의 다음을 「02화」로 쓴다.
  /* 숫자 뒤에 올 수 있는 표기는 다섯 — 이 앱이 짓는 「화」가 첫째다.
     («정규식 리터럴»로 둔다: 템플릿 문자열에 넣으면 \\d가 한 겹 벗겨져 조용히 안 맞는다) */
  const num = /^(.*?)(\d{1,4})\s*([화편회장부])$/.exec(t);
  if (num) {
    const [, stem, digits, marker] = num;
    const pad = digits.length;
    return make(stem, Number(digits), marker, (n) => `${stem}${String(n).padStart(pad, "0")}${marker}`);
  }

  // (2) 괄호 안의 상·중·하 — 「모래성 (상)」. 다음 이름은 상→중→하이고, 「하」 다음은 없다(빈 문자열).
  for (const [l, r] of BRACKETS) {
    const word = WORDS.find((w) => t.endsWith(l + w + r));
    if (!word) continue;
    const stem = t.slice(0, t.length - (l + word + r).length);
    return make(stem, WORDS.indexOf(word) + 1, "상중하", (n) =>
      n >= 1 && n <= WORDS.length ? `${stem}${l}${WORDS[n - 1]}${r}` : "",
    );
  }

  // (3) 표기 없는 끝 숫자 — 「밤의 서점 3」. 앞에 글자와 공백이 있어야 하고 세 자리까지만 본다.
  const bare = /^(.*?[^\d\s])(\s+)(\d{1,3})$/.exec(t);
  if (bare) {
    const [, head, gap, digits] = bare;
    const stem = head + gap;
    const pad = digits.length;
    return make(stem, Number(digits), "", (n) => `${stem}${String(n).padStart(pad, "0")}`);
  }
  return null;
}

/** 다음 화 제목 — 화 표기가 없으면 「… 2화」. 「다음 화 만들기」가 쓰는 규칙이다. */
export function nextEpisodeTitle(title: string): string {
  const p = parseEpisode(title);
  const named = p?.format(p.num + 1) || "";
  // 「(하)」처럼 다음을 쓸 수 없는 표기는 일반 규칙으로 돌아간다 — 감독이 창에서 고칠 수 있다
  return named || `${title.trim()} 2화`;
}

/** 같은 연재를 묶는 열쇠 — 화 표기가 없으면 제목 자체가 열쇠다(목록을 묶을 때 쓴다) */
export function seriesKey(title: string): string {
  return parseEpisode(title)?.key ?? title.trim();
}

/**
 * 이 화의 «다음 화»를 목록에서 찾는다 — 번호가 바로 다음일 필요는 없다(4화를 지웠어도 5화로 잇는다).
 * 같은 연재 중 번호가 더 큰 것들 가운데 가장 작은 것.
 */
export function findNextEpisode<T extends { id: string; title: string }>(
  list: T[],
  current: { id: string; title: string },
): T | undefined {
  const here = parseEpisode(current.title);
  if (!here) return undefined;
  let best: { entry: T; num: number } | undefined;
  for (const e of list) {
    if (e.id === current.id) continue;
    const p = parseEpisode(e.title);
    if (!p || p.key !== here.key || p.num <= here.num) continue;
    if (!best || p.num < best.num) best = { entry: e, num: p.num };
  }
  return best?.entry;
}
