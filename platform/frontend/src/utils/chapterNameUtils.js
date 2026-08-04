const MAX_CHAPTER_NUMBER = 25;

const padChapterNumber = (value) => String(value).padStart(2, '0');

const parseChapterFile = (raw) => {
  if (!raw || typeof raw !== 'string') return null;
  const match = raw.match(/第\s*0?(\d{1,2})章\s*([^_.]+?)(?:[_-].*)?(?:\.pdf)?$/);
  if (!match) return null;
  const number = Number(match[1]);
  if (!Number.isFinite(number)) return null;
  const title = match[2]?.trim() || '';
  return { number, title };
};

const parseExerciseFile = (raw) => {
  if (!raw || typeof raw !== 'string') return null;
  const match = raw.match(/ch(\d{1,2})_習題解答(?:\.pdf)?$/i);
  if (!match) return null;
  const number = Number(match[1]);
  if (!Number.isFinite(number)) return null;
  return { number };
};

const parseModuleName = (raw) => {
  if (!raw || typeof raw !== 'string') return null;
  const match = raw.match(/模組\d+[^.]*?(?=\.pdf|$)/);
  return match ? match[0].trim() : null;
};

export const buildChapterTitleMap = (rawUnits = []) => {
  const map = new Map();
  rawUnits.forEach((raw) => {
    const parsed = parseChapterFile(raw);
    if (!parsed) return;
    if (parsed.number < 1 || parsed.number > MAX_CHAPTER_NUMBER) return;
    if (parsed.title) {
      map.set(parsed.number, parsed.title);
    }
  });
  return map;
};

export const normalizeChapterName = (raw, titleMap) => {
  if (!raw || typeof raw !== 'string') return null;

  const moduleName = parseModuleName(raw);
  if (moduleName) {
    return moduleName;
  }

  const chapterInfo = parseChapterFile(raw);
  if (chapterInfo) {
    if (chapterInfo.number < 1 || chapterInfo.number > MAX_CHAPTER_NUMBER) return null;
    const number = padChapterNumber(chapterInfo.number);
    const title = chapterInfo.title || titleMap?.get(chapterInfo.number) || '';
    return title ? `第${number}章 ${title}` : `第${number}章`;
  }

  const exerciseInfo = parseExerciseFile(raw);
  if (exerciseInfo) {
    if (exerciseInfo.number < 1 || exerciseInfo.number > MAX_CHAPTER_NUMBER) return null;
    const number = padChapterNumber(exerciseInfo.number);
    const title = titleMap?.get(exerciseInfo.number) || '';
    return title ? `第${number}章 ${title}` : `第${number}章`;
  }

  return null;
};

export const parseUnitItems = (value) => {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return [];
    try {
      const parsed = JSON.parse(trimmed);
      return Array.isArray(parsed) ? parsed : [value];
    } catch (error) {
      return [value];
    }
  }
  return [value];
};

export const extractUnitLabel = (item) => {
  if (typeof item === 'string') return item;
  if (item && typeof item === 'object') {
    return item.unit || item.name || item.chapter || null;
  }
  return null;
};

export const getUnitIncrement = (item) => {
  if (item && typeof item === 'object') {
    const rawCount = item.freq ?? item.count ?? item.value ?? 1;
    const parsed = Number(rawCount);
    return Number.isFinite(parsed) ? parsed : 1;
  }
  return 1;
};

export const summarizeChapterCounts = (value, titleMap) => {
  const items = parseUnitItems(value);
  const counts = new Map();
  items.forEach((item) => {
    const rawLabel = extractUnitLabel(item);
    if (!rawLabel) return;
    const normalized = normalizeChapterName(rawLabel, titleMap);
    if (!normalized) return;
    const next = (counts.get(normalized) || 0) + getUnitIncrement(item);
    counts.set(normalized, next);
  });
  return Array.from(counts.entries())
    .map(([unit, count]) => ({ unit, count }))
    .sort((a, b) => (b.count - a.count) || a.unit.localeCompare(b.unit, 'zh-Hant'));
};
