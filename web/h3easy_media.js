import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Visual media panel for "H3 素材加载器". The real values live in the node's
// hidden combo widgets, so saving, loading and queueing work as usual.
// The panel follows the mode of the connected "H3 一键生成" and only shows
// what that mode uses: filled items plus one "add" card until the H3 limit.
// When that node's prompt is a director shot list, the panel lists the files
// the list names instead and says which ones are still missing.
const LOADER = "H3EasyMediaLoader";
const GENERATOR = "H3EasyGenerate";
const MODE_IMAGE = "图文模式（文生 / 首尾帧）";
const MODE_REFERENCE = "参考模式（多图 / 视频参考）";
const NONE = "无";
const LIMIT = { image: 9, video: 3, audio: 3 };
const VIDEO_READ_SECONDS = 15;
const SPARE_FILES = 60;  // pictures a list does not use are stored for later lists up to this many
const MIN_WIDTH = 360;

const FRAMES = [["first_frame", "首帧"], ["last_frame", "尾帧"]];
const REFS = Array.from({ length: LIMIT.image }, (_, i) => `ref_image_${i + 1}`);
const VIDEOS = Array.from({ length: LIMIT.video }, (_, i) => `video_${i + 1}`);
const AUDIOS = Array.from({ length: LIMIT.audio }, (_, i) => `audio_${i + 1}`);
const ALL_SLOTS = [...FRAMES.map((f) => f[0]), ...REFS, ...AUDIOS, ...VIDEOS];
// the loader's hidden number behind its 时长 / 帧数 outputs: seconds of the longest single generation
const CLIP_SECONDS = "clip_seconds";
const ACCEPT = {
    image: "image/*,.png,.jpg,.jpeg,.webp,.bmp",
    audio: "audio/*,video/*,.wav,.mp3,.flac,.ogg,.m4a,.aac,.mp4,.mov",
    video: "video/*,.mp4,.mov,.webm,.mkv,.avi",
    any: "image/*,audio/*,video/*",
};
const DROP_KINDS = { image: ["image"], audio: ["audio", "video"], video: ["video"], any: ["image", "audio", "video"] };

const STYLE = `
.h3e-panel{box-sizing:border-box;width:100%;max-width:100%;overflow:hidden;font:12px/1.4 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:var(--input-text,#ddd);user-select:none}
.h3e-drop{outline:2px dashed #4a9eff;outline-offset:-2px;border-radius:8px}
.h3e-inner{display:flex;flex-direction:column;gap:10px;padding:4px 8px 8px;min-width:0}
.h3e-modebar{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--descrip-text,#999)}
.h3e-pill{flex-shrink:0;white-space:nowrap;padding:1px 8px;border-radius:10px;background:#2b5a8a;color:#fff;font-weight:600}
.h3e-pill.h3e-ref{background:#6b3f8a}
.h3e-pill.h3e-all{background:#555}
.h3e-pill.h3e-sheet{background:#2f7a55}
.h3e-file{display:flex;align-items:center;gap:6px;min-width:0;cursor:pointer;border-radius:6px;padding:2px 4px;border:1px dashed transparent}
.h3e-chip.h3e-ok{background:rgba(127,209,127,.2);color:#7fd17f}
.h3e-chip.h3e-miss{background:rgba(240,179,90,.2);color:#f0b35a}
.h3e-file:hover,.h3e-file.h3e-over{border-color:#4a9eff;background:rgba(74,158,255,.08)}
.h3e-ai{display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:11px;color:var(--descrip-text,#999)}
.h3e-use{position:absolute;right:4px;top:4px;padding:1px 6px;border-radius:6px;background:rgba(0,0,0,.72);color:#fff;font-size:10px;max-width:calc(100% - 8px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.h3e-missing{border-color:#f0b35a;color:#f0b35a}
.h3e-guess{border-color:#f0b35a!important;border-style:dashed}
.h3e-guessmark{position:absolute;left:4px;top:4px;padding:1px 6px;border-radius:6px;background:#f0b35a;color:#222;font-size:10px;z-index:2}
.h3e-shot{display:flex;align-items:center;gap:6px;min-width:0}
.h3e-section{display:flex;flex-direction:column;gap:6px;min-width:0}
.h3e-head{display:flex;align-items:baseline;gap:8px}
.h3e-title{font-weight:600;font-size:13px;white-space:nowrap;flex-shrink:0}
.h3e-hint{color:var(--descrip-text,#999);font-size:11px}
.h3e-grid{display:grid;gap:6px;align-items:start}
.h3e-grid>*{min-width:0}
.h3e-card{position:relative;box-sizing:border-box;min-width:0;min-height:0;border:1px dashed var(--border-color,#555);border-radius:8px;background:var(--comfy-input-bg,#222);overflow:hidden;cursor:pointer;
  display:flex;align-items:center;justify-content:center;color:var(--descrip-text,#999);transition:border-color .15s,background .15s}
.h3e-card:hover,.h3e-over{border-color:#4a9eff!important;background:rgba(74,158,255,.08)}
.h3e-filled{border-style:solid}
.h3e-card img,.h3e-card video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#111;display:block;pointer-events:none}
.h3e-keep{position:absolute;box-sizing:border-box;border:1.5px dashed rgba(255,255,255,.9);box-shadow:0 0 0 999px rgba(0,0,0,.6);pointer-events:none}
.h3e-aspects{display:flex;flex-direction:column;gap:4px}
.h3e-aspect{font-size:11px;color:var(--descrip-text,#aaa);display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.h3e-aspect.h3e-bad{color:#f0b35a}
.h3e-aspect.h3e-good{color:#7fd17f}
.h3e-fit{border:1px solid #4a9eff;background:rgba(74,158,255,.15);color:#cfe3ff;border-radius:6px;padding:1px 8px;cursor:pointer;font:inherit;font-size:11px}
.h3e-fit:hover{background:rgba(74,158,255,.3)}
.h3e-empty{display:flex;flex-direction:column;align-items:center;gap:2px;text-align:center;padding:4px;min-width:0;overflow-wrap:anywhere}
.h3e-plus{font-size:20px;line-height:1;opacity:.8}
.h3e-add-row{min-height:38px;flex-direction:row;gap:6px}
.h3e-add-row .h3e-empty{flex-direction:row;gap:6px}
.h3e-add-tall{min-height:72px}
.h3e-add-row .h3e-plus{font-size:16px}
.h3e-badge{position:absolute;left:4px;bottom:4px;padding:1px 6px;border-radius:6px;background:rgba(0,0,0,.72);color:#fff;font-size:11px;max-width:calc(100% - 16px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.h3e-tag{cursor:copy}
.h3e-card,.h3e-vitem{container-type:inline-size}
.h3e-short{display:none}
@container (max-width:96px){.h3e-tag .h3e-long{display:none}.h3e-tag .h3e-short{display:inline}}
.h3e-tag:hover{background:#2b5a8a}
.h3e-warn{color:#f0b35a}
.h3e-vitem{display:flex;flex-direction:column;gap:3px;min-width:0}
.h3e-caption{display:flex;flex-wrap:wrap;gap:3px;align-items:center;font-size:10px;color:var(--descrip-text,#aaa);overflow:hidden}
.h3e-caption .h3e-chip{font-size:10px;padding:0 5px}
.h3e-x{position:absolute;right:4px;top:4px;width:20px;height:20px;border-radius:10px;border:none;background:rgba(0,0,0,.65);color:#fff;font-size:13px;line-height:20px;text-align:center;cursor:pointer;padding:0;z-index:2}
.h3e-x:hover{background:#d33}
.h3e-play{position:absolute;left:4px;top:4px;width:22px;height:22px;border-radius:11px;border:none;background:rgba(0,0,0,.65);color:#fff;font-size:11px;cursor:pointer;padding:0;z-index:2}
.h3e-audio{position:relative;border:1px solid var(--border-color,#555);border-radius:8px;background:var(--comfy-input-bg,#222);padding:6px 8px;display:flex;flex-direction:column;gap:4px}
.h3e-audio .h3e-x{top:5px;right:5px}
.h3e-line{display:flex;align-items:center;gap:6px;padding-right:24px;min-width:0}
.h3e-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1}
.h3e-chip{flex-shrink:0;padding:0 6px;border-radius:6px;background:rgba(255,255,255,.08);font-size:11px}
.h3e-chip.h3e-tag{background:rgba(74,158,255,.18)}
.h3e-audio audio{width:100%;height:30px}
.h3e-note{font-size:11px;color:var(--descrip-text,#999);padding:4px 8px;border-radius:6px;background:rgba(255,255,255,.04)}
.h3e-foot{display:flex;justify-content:space-between;align-items:center}
.h3e-btn{border:1px solid var(--border-color,#555);background:var(--comfy-input-bg,#222);color:inherit;border-radius:6px;padding:3px 10px;cursor:pointer;font:inherit}
.h3e-btn:hover{border-color:#d33;color:#f88}
.h3e-toast{color:#7fd17f;font-size:11px;opacity:0;transition:opacity .2s}
.h3e-show{opacity:1}
.h3e-moving{opacity:.35}
.h3e-grip{cursor:grab}
`;

function ensureStyle() {
    if (document.getElementById("h3e-style")) return;
    const style = document.createElement("style");
    style.id = "h3e-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function findWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function hideWidget(widget) {
    if (!widget || widget.__h3eHidden) return;
    widget.__h3eHidden = true;
    // ``hidden`` is what both the canvas and the "Nodes 2.0" (Vue) renderer check. Do not
    // retype the widget as "converted-widget": the Vue renderer keeps an empty row for those.
    widget.hidden = true;
    widget.options ||= {};
    widget.options.hidden = true;
    widget.computeSize = () => [0, -4];
}

function getValue(node, name) {
    const value = findWidget(node, name)?.value;
    return value && value !== NONE ? value : null;
}

function setValue(node, name, value) {
    const widget = findWidget(node, name);
    if (!widget) return;
    const v = value || NONE;
    const values = widget.options?.values;
    if (Array.isArray(values) && !values.includes(v)) values.push(v);
    widget.value = v;
    widget.callback?.(v);
}

function splitName(name) {
    const slash = name.lastIndexOf("/");
    return slash >= 0 ? [name.slice(0, slash), name.slice(slash + 1)] : ["", name];
}

// Counts the times an input file was written again under its old name: the address of every
// preview changes with it, so the browser cannot show the picture it remembers.
let rewrites = 0;

function viewUrl(name) {
    const [subfolder, filename] = splitName(name);
    const query = new URLSearchParams({ filename, subfolder, type: "input" });
    if (rewrites) query.set("v", rewrites);
    return api.apiURL(`/view?${query}`);
}

function kindOf(file) {
    const type = file.type || "";
    const name = file.name.toLowerCase();
    if (type.startsWith("image/") || /\.(png|jpe?g|webp|bmp|gif)$/.test(name)) return "image";
    if (type.startsWith("video/") || /\.(mp4|mov|webm|mkv|avi)$/.test(name)) return "video";
    if (type.startsWith("audio/") || /\.(wav|mp3|flac|ogg|m4a|aac)$/.test(name)) return "audio";
    return "other";
}

function formatSeconds(seconds) {
    if (seconds == null || !isFinite(seconds)) return "";
    return seconds >= 60 ? `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}` : `${seconds.toFixed(1)}s`;
}

// ``overwrite`` keeps the file name when one with that name is already there
async function upload(file, overwrite = false, subfolder = "") {
    const body = new FormData();
    // Under its name alone. A file picked together with its folder (the folder button) would be
    // sent under its path inside that folder, and the server takes that path for a folder of its
    // own input directory: one that is not there, so the upload fails with a 500.
    body.append("image", file, file.name.split(/[\\/]/).pop());
    if (overwrite) body.append("overwrite", "true");
    if (subfolder) body.append("subfolder", subfolder);
    const response = await api.fetchApi("/upload/image", { method: "POST", body });
    if (response.status !== 200) throw new Error(`${response.status} ${response.statusText}`);
    const data = await response.json();
    return data.subfolder ? `${data.subfolder}/${data.name}` : data.name;
}

// A dropped folder is opened this many levels down (a shot list next to a folder of pictures
// needs one) and read up to this many files, so a whole drive dropped by mistake stays cheap.
const FOLDER_DEPTH = 3;
const FOLDER_FILES = 500;

// ``folder`` asks for a whole folder instead: everything in it comes back, subfolders included
function pickFiles(kind, multiple, folder = false) {
    return new Promise((resolve) => {
        const input = el("input");
        input.type = "file";
        if (folder) input.webkitdirectory = true;
        else input.accept = ACCEPT[kind];
        input.multiple = !!multiple;
        input.style.display = "none";
        input.onchange = () => {
            const files = Array.from(input.files || []);
            resolve(folder ? files.filter((file) => file.webkitRelativePath.split("/").length - 2 <= FOLDER_DEPTH)
                .slice(0, FOLDER_FILES) : files);
            input.remove();
        };
        input.oncancel = () => {
            resolve([]);
            input.remove();
        };
        document.body.appendChild(input);
        input.click();
    });
}

async function readEntry(entry, depth, out) {
    if (out.length >= FOLDER_FILES) return;
    if (entry.isFile) {
        const file = await new Promise((resolve) => entry.file(resolve, () => resolve(null)));
        if (file) out.push(file);
        return;
    }
    if (!entry.isDirectory || depth < 0) return;
    const reader = entry.createReader();
    // a folder is handed over in batches, until an empty one
    const batch = () => new Promise((resolve) => reader.readEntries(resolve, () => resolve([])));
    for (let entries = await batch(); entries.length; entries = await batch()) {
        for (const child of entries) await readEntry(child, depth - 1, out);
    }
}

const dropsFolder = (e) => Array.from(e.dataTransfer?.items || [])
    .some((item) => item.kind === "file" && item.webkitGetAsEntry?.()?.isDirectory);

// The files of a drop, folders opened. Call it inside the drop handler: the browser gives out
// a drop's folders only while the event is running.
async function droppedFiles(e) {
    const files = Array.from(e.dataTransfer?.files || []);
    const entries = Array.from(e.dataTransfer?.items || []).filter((item) => item.kind === "file")
        .map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
    if (!entries.some((entry) => entry.isDirectory)) return files;
    const out = [];
    for (const entry of entries) await readEntry(entry, FOLDER_DEPTH, out);
    return out;
}

// A director shot list pasted as the prompt starts its cards with a "SHOT 01" line. The
// backend reads it and says which input file stands behind each reference.
const SHEET = /^[\s#>*_-]*SHOT\s*\d+\s*(?:[*_:：（(].*)?$/im;
const SHEETS = new Map();  // prompt text -> what /h3easy/shot_list said (a Promise while loading)

// undefined: an ordinary prompt; null: still loading; otherwise {shots, problems}
function readSheet(text, onReady) {
    if (!SHEET.test(text)) return undefined;
    if (!SHEETS.has(text)) {
        if (SHEETS.size > 8) SHEETS.clear();
        const pending = api.fetchApi("/h3easy/shot_list", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
        })
            .then((r) => (r.ok ? r.json() : { shots: [], problems: [] }))
            .catch(() => ({ shots: [], problems: [] }))
            .then((info) => {
                if (SHEETS.get(text) === pending) SHEETS.set(text, info);
                return info;
            });
        SHEETS.set(text, pending);
    }
    const info = SHEETS.get(text);
    if (info instanceof Promise) {
        info.then(onReady);
        return null;
    }
    return info.shots.length ? info : undefined;
}

// the same as a promise: what the backend read from a shot list, null for an ordinary prompt
function loadSheet(text) {
    return new Promise((resolve) => {
        const info = readSheet(text, (ready) => resolve(ready.shots.length ? ready : null));
        if (info !== null) resolve(info || null);
    });
}

const isSheetFile = (file) => /\.(md|markdown|txt)$/i.test(file.name);
const MEDIA_EXT = /\.(png|jpe?g|webp|bmp|gif|wav|mp3|flac|ogg|m4a|aac|mp4|mov|webm|mkv|avi)$/i;
const promptLinked = (generator) => generator.inputs?.find((i) => i.name === "prompt")?.link != null;

// The shot list among the text files of a drop: one that carries shot cards. A folder may also
// hold the story and notes; of several lists the one named 出片清单 wins, then the newest. The
// AI template shows example cards too and is never the list.
async function findSheet(files) {
    const found = [];
    for (const file of files) {
        if (!isSheetFile(file) || file.size > 2_000_000) continue;
        const text = await file.text();
        if (SHEET.test(text) && !text.includes(TEMPLATE_MARK)) found.push({ file, text });
    }
    const named = (entry) => (entry.file.name.includes("出片清单") ? 1 : 0);
    found.sort((a, b) => named(b) - named(a) || b.file.lastModified - a.file.lastModified);
    return found[0] || null;
}

// one row per file a shot list names, however many shots use it
function sheetRows(info) {
    const rows = new Map();
    for (const shot of info.shots) {
        for (const file of shot.files) {
            const kind = file.tag.slice(1, file.tag.indexOf(" ")).toLowerCase();
            const key = `${kind}/${file.wanted}`;
            if (!rows.has(key)) rows.set(key, { ...file, kind, key, shots: [] });
            rows.get(key).shots.push(shot.number);
        }
    }
    return [...rows.values()];
}

const rowKind = (row) => (row.kind === "picture" ? "image" : row.kind);
const stemOf = (name) => name.split(/[\\/]/).pop().replace(MEDIA_EXT, "");
// file names are compared without case, spaces and the marks people put between words
const plainName = (name) => stemOf(name).normalize("NFKC").toLowerCase().replace(/[\s_\-·.,，、()（）[\]【】]+/g, "");

// ``short`` inside ``long``, but not as a piece of a longer number (图1 is not in 图10)
function nameInside(short, long) {
    const at = long.indexOf(short);
    if (short.length < 2 || at < 0) return false;
    const digit = (c) => c >= "0" && c <= "9";
    const end = at + short.length;
    return !(digit(short[0]) && at > 0 && digit(long[at - 1])) && !(digit(short[short.length - 1]) && end < long.length && digit(long[end]));
}

const CARD_HEAD = /^[\s#>*_-]*SHOT\s*(\d+)\s*(?:[*_:：（(].*)?$/i;
const CARD_LABEL = /^[\s#>*_-]*(Duration|Mode|References|接上一镜|导演意图|分段|已核对|H3\s*Prompt|注意事项)[\s*_]*[:：](.*)$/i;
// A card whose <Picture N> skip a number: an AI that numbers its pictures once for the whole list
// instead of card by card writes <Picture 1>, <Picture 2>, <Picture 4> on a card that uses three.
// The numbers of such a card are closed up, in its References and in its prompt alike. Returns the
// new text, or null when no card needs it.
function closeUpTags(text) {
    const lines = text.split(/\r?\n/);
    const starts = lines.map((line, i) => (CARD_HEAD.test(line) ? i : -1)).filter((i) => i >= 0);
    let changed = false;
    starts.forEach((start, k) => {
        const end = starts[k + 1] ?? lines.length;
        const from = lines.findIndex((line, i) => i > start && i < end && /^[\s#>*_-]*References[\s*_]*[:：]/i.test(line));
        if (from < 0) return;
        let to = lines.findIndex((line, i) => i > from && i < end && CARD_LABEL.test(line));
        if (to < 0) to = end;
        const listed = lines.slice(from, to).join("\n");
        for (const kind of ["Picture", "Video", "Audio"]) {
            const tag = new RegExp(`<\\s*${kind}\\s*(\\d+)\\s*>`, "gi");
            const numbers = [...new Set([...listed.matchAll(tag)].map((m) => Number(m[1])))].sort((a, b) => a - b);
            if (!numbers.length || numbers.every((n, i) => n === i + 1)) continue;
            const now = new Map(numbers.map((n, i) => [n, i + 1]));
            for (let i = start; i < end; i++) {
                lines[i] = lines[i].replace(tag, (whole, n) => (now.has(Number(n)) ? `<${kind} ${now.get(Number(n))}>` : whole));
            }
            changed = true;
        }
    });
    return changed ? lines.join("\n") : null;
}

// Files whose names say nothing (a download from a chat page), paired with the rows of a list that
// still have no file. Only when their numbers are equal, kind by kind: then the file saved first
// goes to the row the list's text names first, which is the order the pictures are made in.
// It is a guess; the panel shows it as one until the user has looked.
function pairInOrder(empty, rest, text) {
    const pairs = [];
    const place = (row) => {
        const at = text.indexOf(stemOf(row.wanted));
        return at < 0 ? Infinity : at;
    };
    for (const kind of ["image", "video", "audio"]) {
        const rows = empty.filter((row) => rowKind(row) === kind).sort((a, b) => place(a) - place(b));
        const files = rest.filter((file) => kindOf(file) === kind)
            .sort((a, b) => a.lastModified - b.lastModified || a.name.localeCompare(b.name, undefined, { numeric: true }));
        if (rows.length && rows.length === files.length) rows.forEach((row, i) => pairs.push([row, files[i]]));
    }
    return pairs;
}

// Which of ``files`` stands behind which row of a shot list, going by file names: the same name
// first (whatever the extension), then one name inside the other (秦伯 (2).jpg and 角色_秦伯.png
// for 秦伯.png). Longer shared names are settled first; of two files for one row the newer wins.
function matchRows(rows, files) {
    const pairs = [];
    for (const row of rows) {
        const want = plainName(row.wanted);
        if (!want) continue;
        for (const file of files) {
            if (!DROP_KINDS[rowKind(row)].includes(kindOf(file))) continue;
            const have = plainName(file.name);
            const score = have === want ? 1000 + want.length
                : nameInside(want, have) ? want.length : nameInside(have, want) ? have.length : 0;
            if (score) pairs.push({ row, file, score });
        }
    }
    pairs.sort((a, b) => b.score - a.score || b.file.lastModified - a.file.lastModified);
    const matched = new Map();
    const used = new Set();
    for (const { row, file } of pairs) {
        if (matched.has(row) || used.has(file)) continue;
        matched.set(row, file);
        used.add(file);
    }
    return { matched, rest: files.filter((file) => !used.has(file)) };
}

// What a user hands to any chat AI to get a shot list back: the single-file NB-H3-Director rules
// (shot_list_template.md, kept word for word). The file says at its top what a reply has to look
// like and has every reply checked at its end, so it reads the same whichever AI gets it and
// wherever it was copied from. All that is added here is that the user works with this plugin,
// which switches on the file's section about it.
// Loaded up front so the copy button can write to the clipboard right inside the click.
const AI_TEMPLATE_HEAD = `（我用 ComfyUI-H3-Easy 插件出片，下面说明里的第 16 节对我生效。）

`;
// how the template starts; a folder that holds a copy of it must not take it for a shot list
const TEMPLATE_MARK = "NB-H3-Director 单文件版";
let aiTemplate = "";
// "no-cache": the server sends this file without cache rules, and a browser would go on handing
// out the copy it has for hours after the plugin was updated
fetch(new URL("./shot_list_template.md", import.meta.url), { cache: "no-cache" }).then((r) => (r.ok ? r.text() : "")).then((text) => {
    aiTemplate = text;
}).catch(() => {});

function setPrompt(generator, text) {
    const widget = findWidget(generator, "prompt");
    widget.value = text;
    widget.callback?.(text);
    writeTakes(generator, new Map());  // another list starts from its first takes
    generator.setDirtyCanvas?.(true, true);
}

// Which take each shot of a list is on, kept in the generator's "镜头版本" widget as "3:2,5:1"
// (a shot that is not named is on its first take). A shot whose take changes is generated again.
function readTakes(generator) {
    const takes = new Map();
    const text = String(findWidget(generator, "shot_versions")?.value || "");
    for (const [, number, take] of text.matchAll(/(\d+)\s*[:：]\s*(\d+)/g)) takes.set(Number(number), Number(take));
    return takes;
}

function writeTakes(generator, takes) {
    const widget = findWidget(generator, "shot_versions");
    if (!widget) return false;
    const text = [...takes].filter(([, take]) => take > 1).sort((a, b) => a[0] - b[0])
        .map(([number, take]) => `${number}:${take}`).join(",");
    if (widget.value !== text) {
        widget.value = text;
        widget.callback?.(text);
        generator.setDirtyCanvas?.(true, true);
    }
    return true;
}

// A number set on a node: its widget, or the node that is wired into it (a float or integer primitive).
function numberOn(node, name) {
    const graph = node.graph;
    const linked = node.inputs?.find((i) => i.name === name)?.link;
    if (linked != null) {
        const link = graph?.getLink?.(linked) ?? graph?.links?.get?.(linked) ?? graph?.links?.[linked];
        const source = link && graph.getNodeById(link.origin_id);
        const value = Number(source?.widgets?.find((w) => typeof w.value === "number")?.value);
        if (isFinite(value)) return value;
    }
    const value = Number(findWidget(node, name)?.value);
    return isFinite(value) ? value : null;
}

// Ask the backend's generation planner, including rounded durations and joins that become cuts.
const RUNS = new WeakMap();
function longestRun(generator, onReady) {
    const text = !promptLinked(generator) && findWidget(generator, "prompt")?.value;
    const seconds = numberOn(generator, "segment_seconds");
    if (!seconds) return null;
    const body = JSON.stringify({ prompt: typeof text === "string" ? text : "",
        segments: numberOn(generator, "segments") || 1, segment_seconds: seconds });
    let run = RUNS.get(generator);
    if (!run || run.body !== body) {
        run = { body, value: null };
        RUNS.set(generator, run);
        run.pending = api.fetchApi("/h3easy/timing", { method: "POST", headers: { "Content-Type": "application/json" }, body })
            .then((r) => r.ok ? r.json() : null)
            .then((info) => {
                if (RUNS.get(generator) !== run) return;
                run.value = info && { ...info, from: typeof text === "string" && SHEET.test(text)
                    ? "清单的实际生成时长" : "「每段秒数」对应的实际生成时长" };
                onReady();
            }).catch(() => {});
    }
    return run.value;
}

async function clipSecondsForQueue(generator, current) {
    let run;
    do {
        longestRun(generator, () => {});
        run = RUNS.get(generator);
        await run?.pending;
        longestRun(generator, () => {});
    } while (run !== RUNS.get(generator));
    return run?.value ? Math.round(run.value.seconds * 1000) / 1000 : current;
}

// duration / soundtrack info from the plugin's /h3easy/media_info route
const INFO = new Map();
function mediaInfo(name, onReady) {
    if (INFO.has(name)) {
        const entry = INFO.get(name);
        if (entry instanceof Promise) entry.then(onReady);
        return entry instanceof Promise ? null : entry;
    }
    const pending = api.fetchApi(`/h3easy/media_info?${new URLSearchParams({ name })}`)
        .then((r) => (r.ok ? r.json() : {}))
        .catch(() => ({}))
        .then((info) => {
            INFO.set(name, info);
            return info;
        });
    INFO.set(name, pending);
    pending.then(onReady);
    return null;
}

// natural pixel size of an input image or video: {w, h}, null when unreadable or still loading
const SIZES = new Map();
function mediaSize(name, kind, onReady) {
    const known = SIZES.get(name);
    if (known instanceof Promise) {
        known.then(onReady);
        return null;
    }
    if (known !== undefined) return known;
    const pending = new Promise((resolve) => {
        const done = (size) => {
            SIZES.set(name, size);
            resolve(size);
        };
        if (kind === "video") {
            const video = document.createElement("video");
            video.preload = "metadata";
            video.muted = true;
            const finish = (size) => {
                video.removeAttribute("src");  // let the browser drop the connection
                video.load();
                done(size);
            };
            video.onloadedmetadata = () => finish(video.videoWidth && video.videoHeight ? { w: video.videoWidth, h: video.videoHeight } : null);
            video.onerror = () => finish(null);
            video.src = viewUrl(name);
        } else {
            const img = new Image();
            img.onload = () => done({ w: img.naturalWidth, h: img.naturalHeight });
            img.onerror = () => done(null);
            img.src = viewUrl(name);
        }
    });
    SIZES.set(name, pending);
    pending.then(onReady);
    return null;
}

// after input files were written over: previews, sizes and durations are read again
function refreshMedia() {
    rewrites += 1;
    SIZES.clear();
    INFO.clear();
    SHEETS.clear();
}

const clampRatio = (ratio) => Math.min(2.5, Math.max(0.4, ratio));
const ratioOf = (size) => (size && size.w > 0 && size.h > 0 ? clampRatio(size.w / size.h) : null);

// Equal columns, one cell shape for the whole grid, so rows and columns line up.
function grid(columns, items) {
    const box = el("div", "h3e-grid");
    box.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
    box.append(...items);
    return box;
}

// cell shape for a grid: the typical (median) shape of its images, so a set of portraits gets
// portrait cells and only an odd one out shows thin bars
function cellRatio(ratios, fallback) {
    const known = ratios.filter(Boolean).sort((a, b) => a - b);
    if (!known.length) return fallback;
    return Math.min(2, Math.max(0.5, known[Math.floor((known.length - 1) / 2)]));
}

// output size with the image's aspect ratio and about the same pixel area, on H3's 32-pixel grid
function sizeForAspect(image, output) {
    const area = output.w * output.h;
    const ratio = image.w / image.h;
    const snap = (v) => Math.min(2048, Math.max(256, Math.round(v / 32) * 32));
    return { w: snap(Math.sqrt(area * ratio)), h: snap(Math.sqrt(area / ratio)) };
}

// the list item being dragged to a new position inside a panel (not a file drag)
let moving = null;
const TAG = /<\s*(Picture|Video|Audio)\s*(\d+)\s*>/gi;

function linkedGenerators(node) {
    const graph = node.graph;
    const out = [];
    for (const id of node.outputs?.[0]?.links || []) {
        const link = graph?.getLink?.(id) ?? graph?.links?.get?.(id) ?? graph?.links?.[id];
        const target = link && graph.getNodeById(link.target_id);
        if (target && (target.comfyClass || target.type) === GENERATOR) out.push(target);
    }
    return out;
}

function loadersFeeding(generator) {
    const graph = generator.graph;
    const input = generator.inputs?.find((i) => i.name === "media");
    if (!graph || !input || input.link == null) return [];
    const link = graph.getLink?.(input.link) ?? graph.links?.get?.(input.link) ?? graph.links?.[input.link];
    const origin = link && graph.getNodeById(link.origin_id);
    return origin && origin.__h3ePanel ? [origin] : [];
}

class MediaPanel {
    constructor(node) {
        this.node = node;
        this.toastEl = el("span", "h3e-toast");  // kept across re-renders
        this.root = el("div", "h3e-panel");
        this.root.__h3ePanel = this;
        this.inner = el("div", "h3e-inner");
        this.root.append(this.inner);
        for (const type of ["dragenter", "dragover", "dragleave", "drop"]) {
            // keep file drops away from ComfyUI's canvas handler (it would open them as workflows)
            this.root.addEventListener(type, (e) => {
                e.preventDefault();
                e.stopPropagation();
            });
        }
        // the panel as a whole takes a batch of files or a folder: show that while they hover
        const hover = (on) => this.root.classList.toggle("h3e-drop", on);
        this.root.addEventListener("dragover", (e) => hover(!moving && !!e.dataTransfer?.types?.includes("Files")));
        this.root.addEventListener("dragleave", (e) => {
            if (!this.root.contains(e.relatedTarget)) hover(false);
        });
        this.root.addEventListener("drop", () => hover(false));
        this.unplaced = [];  // files of a shot list that no row was found for: {file, url}
        this.guessed = new Map();  // rows whose file was paired by order, not by name: row key -> the file's own name
        this.spare = [];  // names of imported files the list does not use, stored for the lists that do
        this.root.addEventListener("drop", (e) => {
            // a card being moved, or one file dropped on a card: the card has dealt with it
            if (moving || e.h3eTaken) return;
            droppedFiles(e).then((files) => this.takeFiles(files));
        });
    }

    // ---------- state helpers ----------
    list(names) {
        return names.map((n) => getValue(this.node, n)).filter(Boolean);
    }

    writeList(names, values) {
        names.forEach((n, i) => setValue(this.node, n, values[i] || null));
    }

    mode() {
        const generators = linkedGenerators(this.node);
        if (!generators.length) return null;
        return findWidget(generators[0], "mode")?.value === MODE_REFERENCE ? "reference" : "image";
    }

    async uploadAll(files, overwrite = false) {
        const names = [];
        const failed = [];
        for (const file of files) {
            try {
                names.push(await upload(file, overwrite));
            } catch (error) {
                console.error("[H3 Easy] upload failed", error);
                failed.push([file.name, error]);
            }
        }
        this.reportFailed(failed);
        return names;
    }

    // one message for everything that did not get through, however many files it was
    reportFailed(failed) {
        if (!failed.length) return;
        const names = failed.slice(0, 8).map(([name]) => name).join("\n") + (failed.length > 8 ? `\n……共 ${failed.length} 个` : "");
        alert(`这 ${failed.length} 个文件没有传上去：\n${names}\n\n原因：${failed[0][1].message ?? failed[0][1]}`);
    }

    // Keep the hidden number behind the 时长 / 帧数 outputs in step with the generator. Returns what
    // it now says, or nothing when this loader has no such outputs (ComfyUI not restarted since the
    // plugin was updated) or no generator to ask.
    syncClip() {
        const widget = findWidget(this.node, CLIP_SECONDS);
        const generator = linkedGenerators(this.node)[0];
        const run = widget && generator && longestRun(generator, () => this.renderSoon());
        if (!run) return null;
        const seconds = Math.round(run.seconds * 1000) / 1000;
        if (widget.value !== seconds) {
            widget.value = seconds;
            this.node.setDirtyCanvas?.(true, true);
        }
        return run;
    }

    clipNote() {
        const run = this.syncClip();
        if (!run) return null;
        const note = el("div", "h3e-note", `「时长」「帧数」输出口现在给出 ${Math.round(run.seconds * 10) / 10} 秒（${run.frames} 帧）：取自${run.from}`);
        note.title = "接到预览一类需要知道片子多长的节点上。用出片清单时跟着清单走，不用清单时跟着「H3 一键生成」的每段秒数走";
        return note;
    }

    // ---------- director shot list ----------
    sheet() {
        const generator = linkedGenerators(this.node)[0];
        const text = generator && !promptLinked(generator) && findWidget(generator, "prompt")?.value;
        return typeof text === "string" ? readSheet(text, () => this.renderSoon()) : undefined;
    }

    // Whatever was dropped on the panel or picked as a folder, in one go: a shot list among the
    // files becomes the generator's prompt; pictures, sound and video go to the rows of the list
    // by file name, or into the panel's own slots when there is no list. ``plain`` lets a lone
    // text file without shot cards be the prompt as well.
    async takeFiles(files, plain = true) {
        if (!files.length) return;
        const media = files.filter((file) => kindOf(file) !== "other");
        const sheet = await findSheet(files);
        const text = sheet ? sheet.text : plain && files.length === 1 && isSheetFile(files[0]) ? await files[0].text() : null;
        const generator = linkedGenerators(this.node)[0];
        const writable = generator && !promptLinked(generator);
        if (text != null && writable) {
            this.clearUnplaced();
            this.guessed.clear();
            this.spare = [];
            setPrompt(generator, text);
        }
        const problem = text == null || writable ? ""
            : generator ? "提示词是连线进来的，清单要放到连过来的那个节点里" : "先把「素材」连到「H3 一键生成」";
        if (!media.length) {
            this.render();
            this.toast(problem || (text != null ? (sheet ? `已读入 ${sheet.file.name}` : "") : "没有认出能用的文件：要出片清单（.md / .txt），或者图片、音频、视频"), 4000);
            return;
        }
        this.toast(`正在导入 ${media.length} 个文件…`, 60000);
        SHEETS.clear();  // which files are already there is asked afresh
        const current = writable && findWidget(generator, "prompt")?.value;
        const info = typeof current === "string" ? await loadSheet(current) : null;
        const report = info ? await this.fillSheet(info, media, current) : await this.addToSlots(media);
        if (info) refreshMedia();
        this.render();
        this.toast([problem, sheet && writable ? `已读入 ${sheet.file.name}` : "", report].filter(Boolean).join("；"), 8000);
    }

    // Files for a shot list, sorted to its rows by name and stored where the list finds them.
    // What no row was found for waits in the panel, to be dragged onto its card.
    async fillSheet(info, files, text = "") {
        const rows = sheetRows(info);
        const { matched, rest: unnamed } = matchRows(rows, files);
        const named = matched.size;
        // what the names do not settle is paired in the order the files were saved (see pairInOrder)
        const empty = rows.filter((row) => !row.found && !matched.has(row));
        const guesses = pairInOrder(empty, unnamed, text);
        for (const [row, file] of guesses) {
            matched.set(row, file);
            this.guessed.set(row.key, file.name);
        }
        const rest = unnamed.filter((file) => !guesses.some((pair) => pair[1] === file));
        // A row of the list is still empty: what is left might be its file, and waits to be dragged
        // there. No row is empty: what is left belongs to the other lists of the same story (one
        // folder of pictures serves them all). It is stored under its own name, so that a later
        // list finds it without another import.
        const open = (kind) => rows.some((row) => !row.found && !matched.has(row) && DROP_KINDS[rowKind(row)].includes(kind));
        const waiting = rest.filter((file) => open(kindOf(file)));
        const spare = rest.filter((file) => !waiting.includes(file));
        const failed = [];
        for (const [row, file] of matched) {
            const error = await this.storeFor(row, file);
            if (error) failed.push([file.name, error]);
        }
        this.reportFailed(failed);
        const kept = spare.length <= SPARE_FILES;
        if (kept) await this.uploadAll(spare, true);
        this.spare = kept ? spare.map((file) => file.name) : [];
        for (const file of waiting) this.unplaced.push({ file, url: kindOf(file) === "image" ? URL.createObjectURL(file) : null });
        const parts = [];
        if (named) parts.push(`按文件名对上 ${named} 个`);
        if (guesses.length) parts.push(`${guesses.length} 个文件名对不上，按存图的先后顺序对到了清单上：卡片标着「猜的」，看一眼图对不对，不对就拖动互换`);
        if (waiting.length) parts.push(`${waiting.length} 个没认出来，放在下面，拖到对应的卡片上`);
        if (spare.length) parts.push(kept ? `另外 ${spare.length} 个这一份清单用不到，已经存好，后面的清单用到时自动对上` : `另外 ${spare.length} 个这一份清单用不到，没有导入`);
        return parts.join("；");
    }

    // A file for one row of the list goes under the name the list asks for, with its own
    // extension: the backend takes the same file name first, then the newest file of that name
    // with another extension. Only when the list's exact file is there and the new one has a
    // different extension is it written over that very file, or the old one would stay in use.
    async storeFor(row, file) {
        const extension = (file.name.match(/\.[^.]+$/) || [""])[0];
        let [subfolder, name] = ["", stemOf(row.wanted) + extension];
        if (row.found) {
            const [folder, current] = splitName(row.found);
            const exact = current.toLowerCase() === row.wanted.split(/[\\/]/).pop().toLowerCase();
            if (exact && current.toLowerCase() !== name.toLowerCase()) [subfolder, name] = [folder, current];
        }
        try {
            await upload(new File([file], name, { type: file.type }), true, subfolder);
            return null;
        } catch (error) {
            console.error("[H3 Easy] upload failed", error);
            return error;
        }
    }

    // a file given to one row of the list by hand
    async bindSheetFile(row, file) {
        if (!file) return;
        this.guessed.delete(row.key);
        const error = await this.storeFor(row, file);
        if (error) this.reportFailed([[file.name, error]]);
        refreshMedia();
        this.render();
    }

    // a file that waited in the panel is dragged onto its card
    async bindUnplaced(row, entry) {
        this.forgetUnplaced(entry);
        await this.bindSheetFile(row, entry.file);
    }

    // A card dragged onto another card: the two rows trade their files. An empty row gets a copy
    // (the input folder has no way to take the file away from the first row).
    async swapRows(from, to) {
        if (from.found === to.found) return;
        this.guessed.delete(from.key);
        this.guessed.delete(to.key);
        const grab = async (row) => new File([await (await fetch(viewUrl(row.found), { cache: "no-store" })).blob()], splitName(row.found)[1]);
        try {
            const [mine, theirs] = [await grab(from), to.found ? await grab(to) : null];
            const error = await this.storeFor(to, mine) || (theirs && await this.storeFor(from, theirs));
            if (error) throw error;
        } catch (error) {
            console.error("[H3 Easy] swap failed", error);
            refreshMedia();
            this.render();
            this.toast("没换成，刷新页面再试", 4000);
            return;
        }
        refreshMedia();
        this.render();
        this.toast(to.found ? `「${stemOf(from.wanted)}」和「${stemOf(to.wanted)}」的图已互换` : `已放到「${stemOf(to.wanted)}」`, 3000);
    }

    forgetUnplaced(entry) {
        if (entry.url) URL.revokeObjectURL(entry.url);
        this.unplaced = this.unplaced.filter((other) => other !== entry);
    }

    clearUnplaced() {
        for (const entry of this.unplaced) this.forgetUnplaced(entry);
    }

    // Files dropped on the panel when there is no shot list: each goes where the mode has room for
    // its kind, after what is already there.
    async addToSlots(files) {
        const by = { image: [], video: [], audio: [] };
        for (const file of files) by[kindOf(file)]?.push(file);
        const added = (left) => (files.length > left ? `已加入 ${files.length - left} 个` : "");
        let left = 0;
        const fill = async (names, list) => {
            const values = this.list(names);
            const room = names.length - values.length;
            left += Math.max(0, list.length - room);
            values.push(...await this.uploadAll(list.slice(0, Math.max(0, room))));
            this.writeList(names, values);
        };
        if (this.mode() === "image") {
            // first frame, then last frame; a sound file locks the soundtrack
            for (const [slot] of FRAMES) {
                if (!by.image.length || getValue(this.node, slot)) continue;
                setValue(this.node, slot, (await this.uploadAll([by.image.shift()]))[0] || null);
            }
            if (by.audio.length && !getValue(this.node, AUDIOS[0])) setValue(this.node, AUDIOS[0], (await this.uploadAll([by.audio.shift()]))[0] || null);
            left = by.image.length + by.audio.length + by.video.length;
            return added(left) + (left ? `；图文模式只放首帧、尾帧和一段锁定音频，多出来的 ${left} 个没有加` : "");
        }
        await fill(REFS, by.image);
        await fill(VIDEOS, by.video);
        await fill(AUDIOS, by.audio);
        return added(left) + (left ? `；放满了（图 ${LIMIT.image} 张、视频 ${LIMIT.video} 段、音频 ${LIMIT.audio} 段），多出来的 ${left} 个没有加` : "");
    }

    // the folder a shot list was saved in, picked whole: the list and the pictures next to it
    async importFolder() {
        const files = await pickFiles("any", true, true);
        if (files.length) await this.takeFiles(files, false);
    }

    // one row per shot, with a button to generate that shot again
    shotsSection(info) {
        const takes = readTakes(linkedGenerators(this.node)[0]);
        const section = this.section("镜头", "不满意哪个就点「重抽」再运行，只重新生成它");
        info.shots.forEach((shot, index) => {
            const take = takes.get(shot.number) || 1;
            const line = el("div", "h3e-shot");
            const join = index === 0 ? "开头" : shot.continues ? "续写" : "硬切";
            line.append(el("span", "h3e-name", `镜头 ${shot.number} · ${shot.seconds ?? "?"} 秒 · ${join}`));
            if (take > 1) {
                const back = el("button", "h3e-fit", "上一版");
                back.title = "回到上一版。生成过的版本都留着，不用重新生成";
                back.addEventListener("click", () => this.setTakes(info, new Map([[shot.number, take - 1]])));
                line.append(el("span", "h3e-chip", `第 ${take} 版`), back);
            }
            const again = el("button", "h3e-fit", "重抽");
            again.title = "换一个随机种子重新生成这个镜头，别的镜头不动";
            again.addEventListener("click", () => this.setTakes(info, new Map([[shot.number, take + 1]])));
            line.append(again);
            section.append(line);
        });
        const all = el("button", "h3e-fit", "全部重抽");
        all.title = "每个镜头都换一个随机种子。换了模型、文本编码器或 VAE 想整份重新生成时也点这个";
        all.addEventListener("click", () => this.setTakes(info,
            new Map(info.shots.map((shot) => [shot.number, (takes.get(shot.number) || 1) + 1]))));
        const row = el("div", "h3e-shot");
        row.append(all);
        section.append(row);
        return section;
    }

    setTakes(info, changed) {
        const generator = linkedGenerators(this.node)[0];
        const takes = readTakes(generator);
        for (const [number, take] of changed) takes.set(number, take);
        if (!writeTakes(generator, takes)) {
            this.toast("「H3 一键生成」上没有「镜头版本」这一项：重启 ComfyUI 并重新放一个节点", 5000);
            return;
        }
        this.render();
        if (changed.size > 1) {
            this.toast("所有镜头都换了新版本，点运行全部重新生成", 4000);
            return;
        }
        const [number, take] = [...changed][0];
        // a shot that continues this one starts from its last frames, so it is redone as well
        const tail = [];
        for (let i = info.shots.findIndex((shot) => shot.number === number) + 1; i < info.shots.length && info.shots[i].continues; i++) {
            tail.push(info.shots[i].number);
        }
        this.toast(`镜头 ${number} 换到第 ${take} 版，点运行只重新生成它`
            + (tail.length ? `和接着它续写的镜头 ${tail.join("、")}` : ""), 5000);
    }

    // Click or drop on one of the list's files to supply it. A filled one can be dragged onto
    // another to trade files, and a file that waits below can be dragged onto it.
    bindable(target, row) {
        const kind = rowKind(row);
        target.dataset.h3eRow = row.key;
        target.title = (row.found ? `${row.wanted}\n用的是 input/${row.found}` : `${row.wanted}\ninput 文件夹里没有这个文件`)
            + "\n点击选文件，或把文件拖到这里：会按这个名字存进去"
            + "\n在别处复制了图片：鼠标停在这里按 Ctrl+V，直接贴上，不用下载、不用改名"
            + (row.found ? "\n放错了：拖到另一张卡片上，两张互换" : "");
        target.addEventListener("click", async () => this.bindSheetFile(row, (await pickFiles(kind, false))[0]));
        this.dropTarget(target, kind, (files) => this.bindSheetFile(row, files[0]), (moved) => {
            if (moved.unplaced) return DROP_KINDS[kind].includes(kindOf(moved.unplaced.file)) && (() => this.bindUnplaced(row, moved.unplaced));
            return moved.row && moved.row.key !== row.key && moved.row.kind === row.kind && (() => this.swapRows(moved.row, row));
        });
        if (row.found) this.movable(target, { row });
    }

    // The name a row's file has to carry, to click and copy: for the "save as" box of a browser,
    // or the file name prefix of the node that saves the picture. A file whose name holds it is
    // recognised on import.
    nameTag(row, className, text) {
        const tag = el("span", `${className} h3e-tag`, text);
        const stem = stemOf(row.wanted);
        tag.title = `点击复制「${stem}」：存图时用这个名字，导入时会自动对上`;
        tag.addEventListener("click", (e) => {
            e.stopPropagation();
            this.copy(stem);
        });
        return tag;
    }

    // a picture copied somewhere else and pasted with the mouse over the panel (see the paste listener)
    async pasteFiles(files, key) {
        const info = this.sheetShown && this.sheet();
        const row = key && info ? sheetRows(info).find((item) => item.key === key) : null;
        if (!row) {
            await this.takeFiles(files);
            return;
        }
        const file = files.find((item) => DROP_KINDS[rowKind(row)].includes(kindOf(item)));
        if (!file) {
            this.toast("剪贴板里的东西和这张卡片不是一类", 3000);
            return;
        }
        await this.bindSheetFile(row, file);
        this.toast(`已贴到「${stemOf(row.wanted)}」`, 3000);
    }

    // what keeps a list from running, with a button for the one fix the panel can make itself
    problemsSection(text, info) {
        const box = el("div", "h3e-aspects");
        const closed = closeUpTags(text);
        if (closed) {
            const top = el("div", "h3e-aspect h3e-bad");
            const renumber = el("button", "h3e-fit", "自动改好编号");
            renumber.title = "有镜头的 <Picture N> 跳号了（例如 1、2、4）。点这里把它改成从 1 连续排，清单和提示词里一起改，不用找 AI";
            renumber.addEventListener("click", () => {
                setPrompt(linkedGenerators(this.node)[0], closed);
                this.render();
                this.toast("已把跳号的编号改成从 1 连续排，References 和提示词里一起改了", 5000);
            });
            top.append(el("span", "", "有镜头的图片编号跳号了。"), renumber);
            box.append(top);
        }
        for (const problem of info.problems) box.append(el("div", "h3e-aspect h3e-bad", problem));
        return box;
    }

    // files of an import that no row was found for, each to be dragged onto its card
    unplacedSection() {
        const section = this.section(`没认出来的 ${this.unplaced.length} 个`, "上面还有缺的卡片：是它的就拖上去；这份清单用不到的点 × 关掉");
        section.append(grid(4, this.unplaced.map((entry) => {
            const card = el("div", "h3e-card h3e-filled");
            card.style.aspectRatio = "1";
            if (entry.url) {
                const img = el("img");
                img.src = entry.url;
                card.append(img);
            } else {
                card.append(el("div", "h3e-plus", kindOf(entry.file) === "video" ? "🎬" : "🎵"));
            }
            card.title = `${entry.file.name}\n拖到它该在的那张卡片上；不要就点 ×`;
            card.append(this.removeButton(() => {
                this.forgetUnplaced(entry);
                this.render();
            }), el("span", "h3e-badge", entry.file.name));
            this.movable(card, { unplaced: entry });
            return card;
        })));
        return section;
    }

    // "一键导入": the folder a shot list was saved in, with the pictures next to it
    importRow() {
        const row = el("div", "h3e-ai");
        const folder = el("button", "h3e-fit", "导入文件夹");
        folder.title = "选出片清单所在的文件夹：清单和里面的图片、音频、视频一次导入，按文件名自动对上。\n也可以把整个文件夹直接拖到这个面板上";
        folder.addEventListener("click", () => this.importFolder());
        row.append(el("span", "", "一键导入："), folder, el("span", "", "或把整个文件夹（清单 + 图）拖到面板上"));
        return row;
    }

    sheetCard(row, ratio) {
        const guess = row.found && this.guessed.get(row.key);
        const card = el("div", `h3e-card ${row.found ? "h3e-filled" : "h3e-missing"}${guess ? " h3e-guess" : ""}`);
        card.style.aspectRatio = String(ratio);
        if (row.found) {
            const media = el(row.kind === "video" ? "video" : "img");
            if (row.kind === "video") {
                media.muted = true;
                media.preload = "metadata";
            }
            media.src = viewUrl(row.found);
            card.append(media);
        } else {
            const empty = el("div", "h3e-empty");
            empty.append(el("div", "h3e-plus", "缺"), el("div", "", "点击选择、拖到这里，或 Ctrl+V 粘贴"));
            card.append(empty);
        }
        card.append(this.nameTag(row, "h3e-badge", row.wanted), el("span", "h3e-use", `镜头 ${row.shots.join("、")}`));
        if (guess) {
            const mark = el("span", "h3e-guessmark", "猜的");
            mark.title = `这张图的文件名（${guess}）和清单对不上，是按存图的先后顺序放到这里的。\n不对就把它拖到该在的卡片上，两张互换`;
            card.append(mark);
        }
        this.bindable(card, row);
        return card;
    }

    // "can't write prompts": hand the director rules to a chat AI, paste its shot list back
    aiRow() {
        const row = el("div", "h3e-ai");
        const template = () => {
            if (!aiTemplate) this.toast("模板没读到，刷新页面再试", 3000);
            return aiTemplate && AI_TEMPLATE_HEAD + aiTemplate;
        };
        const copy = el("button", "h3e-fit", "复制 AI 模板");
        copy.title = "把导演规则复制下来，粘贴给豆包、DeepSeek、Kimi、ChatGPT 等任意 AI，再把剧情发给它（有参考图一起发，没有它会先写出图提示词）";
        copy.addEventListener("click", () => {
            const text = template();
            if (!text) return;
            navigator.clipboard.writeText(text).then(
                () => this.toast("已复制。粘贴给任意 AI，再发剧情（有参考图一起发）；它嫌太长就点「下载模板」发文件", 6000),
                () => this.toast("浏览器不让复制，点「下载模板」把文件发给 AI", 5000));
        });
        const save = el("button", "h3e-fit", "下载模板");
        save.title = "模板有近七万字，有的 AI 不让粘贴这么长：下载成文件，把文件发给它";
        save.addEventListener("click", () => {
            const text = template();
            if (!text) return;
            const link = el("a");
            link.href = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
            link.download = "H3导演模板.md";
            link.click();
            setTimeout(() => URL.revokeObjectURL(link.href), 1000);
            this.toast("已下载 H3导演模板.md。把这个文件发给 AI，再发剧情（有参考图一起发）", 6000);
        });
        const paste = el("button", "h3e-fit", "粘贴清单");
        paste.title = "把 AI 回的出片清单整框复制好，点这里填进「H3 一键生成」的提示词；再把参考图一起拖到面板上";
        paste.addEventListener("click", async () => {
            const generator = linkedGenerators(this.node)[0];
            if (!generator || promptLinked(generator)) {
                this.toast(generator ? "提示词是连线进来的，清单要放到连过来的那个节点里" : "先把「素材」连到「H3 一键生成」", 3000);
                return;
            }
            let text;
            try {
                text = await navigator.clipboard.readText();
            } catch {
                this.toast("浏览器不让读剪贴板：点一下提示词框，按 Ctrl+V 粘贴", 5000);
                return;
            }
            if (!SHEET.test(text)) {
                this.toast("剪贴板里不是出片清单（要有 SHOT 01 这样的镜头卡）", 4000);
                return;
            }
            setPrompt(generator, text);
            this.render();
        });
        row.append(el("span", "", "不会写提示词："), copy, save, paste);
        return row;
    }

    renderSheet(info) {
        const inner = this.inner;
        inner.replaceChildren();
        const bar = el("div", "h3e-modebar");
        bar.append(el("span", "h3e-pill h3e-sheet", "出片清单"));
        inner.append(bar);
        if (info) {
            const rows = sheetRows(info);
            const sheetText = String(findWidget(linkedGenerators(this.node)[0], "prompt")?.value || "");
            const missing = rows.filter((row) => !row.found).length;
            const total = info.shots.reduce((sum, shot) => sum + (shot.seconds || 0), 0);
            bar.append(el("span", "", `${info.shots.length} 个镜头，共 ${Math.round(total)} 秒，素材 ${rows.length - missing}/${rows.length}`
                + (missing ? "，把图一起拖到面板上，按文件名自动对上" : info.problems.length ? "，先处理下面的问题" : "，可以运行")));
            inner.append(this.problemsSection(sheetText, info));
            const section = this.section("清单里的素材", "放错了：把一张卡片拖到另一张上，两张互换");
            // pictures and videos as cards, like the ordinary panel; audio as rows
            const visual = rows.filter((row) => row.kind !== "audio");
            const ratio = cellRatio(visual.map((row) => row.found
                && ratioOf(mediaSize(row.found, row.kind === "video" ? "video" : "image", () => this.renderSoon()))), 1);
            if (visual.length) section.append(grid(visual.length <= 4 ? 2 : 3, visual.map((row) => this.sheetCard(row, ratio))));
            for (const row of rows) {
                if (row.kind !== "audio") continue;
                const line = el("div", "h3e-file");
                this.bindable(line, row);
                line.append(el("span", `h3e-chip ${row.found ? "h3e-ok" : "h3e-miss"}`, row.found ? "✓" : "缺"),
                    this.nameTag(row, "h3e-name", `🎵 ${row.wanted}`), el("span", "h3e-hint", `镜头 ${row.shots.join("、")}`));
                section.append(line);
            }
            const guesses = rows.filter((row) => row.found && this.guessed.has(row.key)).length;
            if (guesses) {
                const line = el("div", "h3e-aspect h3e-bad");
                const fine = el("button", "h3e-fit", "都对");
                fine.title = "看过了，图和名字都对得上：去掉「猜的」标记";
                fine.addEventListener("click", () => {
                    this.guessed.clear();
                    this.render();
                });
                line.append(el("span", "", `${guesses} 张图不是按名字认出来的：按存图的先后顺序，对到了清单里素材的顺序上。`
                    + "看一眼卡片上的图对不对，不对就把一张拖到另一张上互换。"), fine);
                section.append(line);
            }
            section.append(this.addCard("any", "把所有图、音频、视频一起拖到面板上，或点这里选（可多选）", "h3e-add-row", true,
                (files) => this.takeFiles(files, false)));
            inner.append(section);
            if (this.spare.length) {
                const names = this.spare.slice(0, 4).map((name) => stemOf(name)).join("、") + (this.spare.length > 4 ? "……" : "");
                inner.append(el("div", "h3e-note", `上面只列这一份清单用到的 ${rows.length} 个素材。一起导入的另外 ${this.spare.length} 个（${names}）`
                    + "这一份用不到，不用往里加：已经存好，后面的清单用到时会自动对上。"));
            }
            if (this.unplaced.length) inner.append(this.unplacedSection());
            inner.append(this.shotsSection(info));
            const own = ALL_SLOTS.filter((name) => getValue(this.node, name)).length;
            if (own) inner.append(el("div", "h3e-note", `面板里原来放的 ${own} 个素材不参与出片清单，提示词换回普通写法后恢复显示`));
        } else {
            bar.append(el("span", "", "正在读取…"));
        }
        const clip = this.clipNote();
        if (clip) inner.append(clip);
        inner.append(this.importRow(), this.aiRow());
        const foot = el("div", "h3e-foot");
        const clear = el("button", "h3e-btn", "清空清单");
        clear.title = "清空提示词里的出片清单，面板回到普通模式";
        clear.addEventListener("click", () => {
            setPrompt(linkedGenerators(this.node)[0], "");
            this.render();
        });
        foot.append(this.toastEl, clear);
        inner.append(foot);
        this.fit();
    }

    async setSingle(slot, files) {
        const [name] = await this.uploadAll(files.slice(0, 1));
        if (!name) return;
        setValue(this.node, slot, name);
        this.render();
    }

    // one file replaces entry ``index``; several files, or index === list length, are appended
    async putInList(names, index, files) {
        const replace = files.length === 1 && index < this.list(names).length;
        const room = replace ? 1 : names.length - this.list(names).length;
        const uploaded = await this.uploadAll(files.slice(0, room));
        if (uploaded.length) {
            const values = this.list(names);
            if (replace) values[index] = uploaded[0];
            else values.push(...uploaded);
            this.writeList(names, values.slice(0, names.length));
            this.render();
        }
        if (files.length > room) this.toast(`放满了，多出来的 ${files.length - room} 个没有加`, 4000);
    }

    removeFromList(names, index) {
        const values = this.list(names);
        values.splice(index, 1);
        this.writeList(names, values);
        this.render();
    }

    moveInList(names, from, to) {
        const values = this.list(names);
        if (from === to || from >= values.length || to >= values.length) return;
        const order = values.map((_, i) => i);  // order[k] = old index now at position k
        order.splice(to, 0, order.splice(from, 1)[0]);
        const maps = this.labelMaps(names, values, order);
        this.writeList(names, order.map((i) => values[i]));
        const result = this.renumberPrompts(maps);
        this.render();
        this.toast(result === "updated" ? "已调整顺序，提示词里的编号已跟着改"
            : result === "linked" ? "已调整顺序（提示词来自连线，编号请手动改）" : "已调整顺序", 2500);
    }

    // old tag number -> new tag number per tag type, for a reorder of one list
    labelMaps(names, values, order) {
        const moved = {};
        order.forEach((old, k) => { moved[old + 1] = k + 1; });
        if (names === REFS) return { picture: moved };
        // <Audio j>: soundtracks of the videos that have one come first, then standalone audio
        const videos = names === VIDEOS ? values : this.list(VIDEOS);
        const infos = videos.map((name) => mediaInfo(name, () => {}));
        const known = infos.every(Boolean);
        if (names === VIDEOS) {
            const audio = {};
            if (known) {
                const label = (list) => {
                    let next = 0;
                    return list.map((i) => (infos[i].has_audio ? ++next : null));
                };
                const before = label(values.map((_, i) => i));
                const after = label(order);
                order.forEach((old, k) => { if (before[old]) audio[before[old]] = after[k]; });
            }
            return { video: moved, audio };
        }
        if (!known) return {};
        const offset = infos.filter((info) => info.has_audio).length;
        const audio = {};
        for (const [old, now] of Object.entries(moved)) audio[Number(old) + offset] = now + offset;
        return { audio };
    }

    renumberPrompts(maps) {
        let result = null;
        for (const generator of linkedGenerators(this.node)) {
            const widget = findWidget(generator, "prompt");
            if (!widget || typeof widget.value !== "string") continue;
            if (generator.inputs?.find((i) => i.name === "prompt")?.link != null) {
                result = result || "linked";
                continue;
            }
            const text = widget.value.replace(TAG, (tag, kind, n) => {
                const now = maps[kind.toLowerCase()]?.[n];
                return now ? `<${kind[0].toUpperCase()}${kind.slice(1).toLowerCase()} ${now}>` : tag;
            });
            if (text !== widget.value) {
                widget.value = text;
                widget.callback?.(text);
                generator.setDirtyCanvas?.(true, true);
                result = "updated";
            }
        }
        return result;
    }

    // ---------- small builders ----------
    // One file dropped on ``target`` goes to ``onFiles``. ``take`` is asked about an item of this
    // panel that is dragged here (see movable): it returns what to do when the item is dropped,
    // or nothing when the item does not belong here.
    dropTarget(target, kind, onFiles, take = null) {
        const action = () => (moving.panel === this && take?.(moving)) || null;
        target.addEventListener("dragover", (e) => {
            if (moving && !action()) return;
            if (moving && e.dataTransfer) e.dataTransfer.dropEffect = "move";
            target.classList.add("h3e-over");
        });
        target.addEventListener("dragleave", () => target.classList.remove("h3e-over"));
        target.addEventListener("drop", (e) => {
            target.classList.remove("h3e-over");
            if (moving) {
                action()?.();
                return;
            }
            // one file is meant for the item it lands on; several files or a folder are for the
            // whole panel, which sorts them out (the root's drop handler)
            const files = Array.from(e.dataTransfer?.files || []);
            if (files.length !== 1 || !DROP_KINDS[kind].includes(kindOf(files[0]))) return;
            e.h3eTaken = true;
            onFiles(files);
        });
    }

    // for dropTarget: an entry of the list ``names`` dragged here moves to position ``index``
    slotTake(names, index) {
        return (moved) => moved.names === names && (() => this.moveInList(names, moved.index, index));
    }

    // Let an item be dragged onto another item of the panel. ``what`` says what is on the move:
    // {names, index} an entry of a list, {row} a file of a shot list, {unplaced} a file that
    // waits for its card. The item it is dropped on decides what happens.
    movable(handle, what, item = handle) {
        handle.draggable = true;
        handle.classList.add("h3e-grip");
        // keep the node from starting its own drag
        handle.addEventListener("pointerdown", (e) => e.stopPropagation());
        handle.addEventListener("dragstart", (e) => {
            e.stopPropagation();
            moving = { panel: this, ...what };
            if (e.dataTransfer) {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/x-h3e-move", "1");
                if (item !== handle) e.dataTransfer.setDragImage(item, 12, 12);
            }
            item.classList.add("h3e-moving");
        });
        handle.addEventListener("dragend", () => {
            moving = null;
            item.classList.remove("h3e-moving");
            this.root.querySelectorAll(".h3e-over").forEach((n) => n.classList.remove("h3e-over"));
        });
    }

    removeButton(onRemove) {
        const x = el("button", "h3e-x", "×");
        x.title = "移除";
        x.addEventListener("click", (e) => {
            e.stopPropagation();
            onRemove();
        });
        return x;
    }

    // ``short`` is shown instead of ``text`` on narrow cards; a click always copies ``text``
    tag(text, className = "h3e-badge", short = null) {
        const badge = el("span", `${className} h3e-tag`);
        if (short) badge.append(el("span", "h3e-long", text), el("span", "h3e-short", short));
        else badge.textContent = text;
        badge.title = `点击复制 ${text}，粘贴到提示词里`;
        badge.dataset.text = text;
        badge.addEventListener("click", (e) => {
            e.stopPropagation();
            this.copy(text);
        });
        return badge;
    }

    addCard(kind, label, shape, multiple, onFiles, take = null) {
        const card = el("div", `h3e-card ${shape || ""}`);
        const empty = el("div", "h3e-empty");
        empty.append(el("div", "h3e-plus", "+"), el("div", "", label));
        card.append(empty);
        card.title = "点击选择文件，或把文件拖到这里";
        card.addEventListener("click", async () => {
            const files = await pickFiles(kind, multiple);
            if (files.length) onFiles(files);
        });
        this.dropTarget(card, kind, onFiles, take);
        return card;
    }

    imageCard(value, shape, badge, onFiles, onRemove, slot = null) {
        const card = el("div", `h3e-card h3e-filled ${shape || ""}`);
        const img = el("img");
        img.src = viewUrl(value);
        img.alt = typeof badge === "string" ? badge : badge.dataset.text;
        card.title = slot ? `${value}\n点击替换，拖到别的图上调整顺序` : `${value}\n点击替换`;
        card.append(img, this.removeButton(onRemove), typeof badge === "string" ? el("span", "h3e-badge", badge) : badge);
        card.addEventListener("click", async () => onFiles(await pickFiles("image", false)));
        this.dropTarget(card, "image", onFiles, slot && this.slotTake(slot.names, slot.index));
        if (slot) this.movable(card, slot);
        return card;
    }

    section(title, hint) {
        const section = el("div", "h3e-section");
        const head = el("div", "h3e-head");
        head.append(el("span", "h3e-title", title));
        if (hint) head.append(el("span", "h3e-hint", hint));
        section.append(head);
        return section;
    }

    // ---------- sections ----------
    framesSection() {
        const section = this.section("首帧 / 尾帧", "都不放＝文生视频");
        const values = FRAMES.map(([slot]) => getValue(this.node, slot));
        const ratios = values.map((value) => value && ratioOf(mediaSize(value, "image", () => this.renderSoon())));
        const output = this.outputSize(linkedGenerators(this.node)[0]);
        const outputRatio = output?.w > 0 && output?.h > 0 ? clampRatio(output.w / output.h) : null;
        // both cards share one shape: the first frame's, else the last frame's, else the output's
        const ratio = ratios[0] || ratios[1] || outputRatio || 16 / 10;
        const items = FRAMES.map(([slot, label], i) => {
            const card = values[i]
                ? this.imageCard(values[i], "h3e-frame", label, (f) => this.setSingle(slot, f), () => {
                    setValue(this.node, slot, null);
                    this.render();
                })
                : this.addCard("image", label, "h3e-frame", false, (f) => this.setSingle(slot, f));
            card.style.aspectRatio = String(ratio);
            const size = values[i] && mediaSize(values[i], "image", () => this.renderSoon());
            if (size && output?.w > 0 && output?.h > 0) this.cropPreview(card, size, ratio, output.w / output.h);
            return card;
        });
        section.append(grid(2, items));
        const aspects = this.frameAspects();
        if (aspects) section.append(aspects);
        return section;
    }

    // Dim the parts of a frame that will be cut off: the run crops it to the output's aspect ratio.
    cropPreview(card, size, cardRatio, outRatio) {
        const imgRatio = size.w / size.h;
        if (Math.abs(Math.log(imgRatio / outRatio)) <= 0.05) return;
        // the image box inside the card (object-fit: contain), then the kept part of the image
        const iw = imgRatio > cardRatio ? 1 : imgRatio / cardRatio;
        const ih = imgRatio > cardRatio ? cardRatio / imgRatio : 1;
        const kw = imgRatio > outRatio ? outRatio / imgRatio : 1;
        const kh = imgRatio > outRatio ? 1 : imgRatio / outRatio;
        const keep = el("div", "h3e-keep");
        Object.assign(keep.style, {
            width: `${iw * kw * 100}%`, height: `${ih * kh * 100}%`,
            left: `${(1 - iw * kw) * 50}%`, top: `${(1 - ih * kh) * 50}%`,
        });
        keep.title = "运行时只保留虚线框内的部分（居中裁切成输出比例）";
        card.querySelector("img")?.after(keep);
    }

    // where the generator's width/height come from: its own widgets, a Resolution Selector, or another node
    outputSize(generator) {
        if (!generator) return null;
        const widthInput = generator.inputs?.find((i) => i.name === "width");
        const heightInput = generator.inputs?.find((i) => i.name === "height");
        const linked = widthInput?.link != null || heightInput?.link != null;
        if (!linked) {
            return { kind: "widgets", w: Number(findWidget(generator, "width")?.value), h: Number(findWidget(generator, "height")?.value) };
        }
        const graph = generator.graph;
        const linkId = widthInput?.link ?? heightInput?.link;
        const link = graph?.getLink?.(linkId) ?? graph?.links?.get?.(linkId) ?? graph?.links?.[linkId];
        const source = link && graph.getNodeById(link.origin_id);
        const aspect = source && findWidget(source, "aspect_ratio");
        const megapixels = source && findWidget(source, "megapixels");
        if (aspect && megapixels) {
            // same arithmetic as ComfyUI's Resolution Selector
            const match = String(aspect.value).match(/^(\d+):(\d+)/);
            const multiple = Number(findWidget(source, "multiple")?.value) || 8;
            if (match) {
                const [rw, rh] = [Number(match[1]), Number(match[2])];
                const scale = Math.sqrt((Number(megapixels.value) * 1024 * 1024) / (rw * rh));
                return {
                    kind: "selector", source, aspect,
                    w: Math.round((rw * scale) / multiple) * multiple,
                    h: Math.round((rh * scale) / multiple) * multiple,
                };
            }
        }
        return { kind: "external", source };
    }

    // how to give the output the image's aspect ratio: {target, title, apply}, or null when it already
    // matches or the size comes from a node the panel can't change
    aspectPlan(size, output, generator) {
        if (!output || !generator) return null;
        if (output.kind === "widgets") {
            if (Math.abs(Math.log((size.w / size.h) / (output.w / output.h))) <= 0.05) return null;
            const target = sizeForAspect(size, output);
            return {
                target: `输出改为 ${target.w}×${target.h}`,
                title: "修改「H3 一键生成」的宽和高（画面总面积基本不变）",
                apply: () => {
                    for (const [name, v] of [["width", target.w], ["height", target.h]]) {
                        const widget = findWidget(generator, name);
                        if (!widget) continue;
                        widget.value = v;
                        widget.callback?.(v);
                    }
                    generator.setDirtyCanvas?.(true, true);
                    this.render();
                },
            };
        }
        if (output.kind === "selector") {
            const ratio = size.w / size.h;
            const options = (output.aspect.options?.values || []).map((v) => {
                const m = String(v).match(/^(\d+):(\d+)/);
                return m ? { value: v, label: `${m[1]}:${m[2]}`, ratio: Number(m[1]) / Number(m[2]) } : null;
            }).filter(Boolean);
            if (!options.length) return null;
            const best = options.reduce((a, b) => (Math.abs(Math.log(b.ratio / ratio)) < Math.abs(Math.log(a.ratio / ratio)) ? b : a));
            if (best.value === output.aspect.value) return null;
            return {
                target: `分辨率选择器改为 ${best.label}`,
                title: `宽高由「${output.source.title || output.source.type}」提供，改它的宽高比`,
                apply: () => {
                    output.aspect.value = best.value;
                    output.aspect.callback?.(best.value);
                    output.source.setDirtyCanvas?.(true, true);
                    this.render();
                },
            };
        }
        return null;
    }

    fixButton(label, size, output, generator) {
        const plan = this.aspectPlan(size, output, generator);
        if (!plan) return null;
        const button = el("button", "h3e-fit", `按${label}比例把${plan.target}`);
        button.title = plan.title;
        button.addEventListener("click", (e) => {
            e.stopPropagation();
            plan.apply();
        });
        return button;
    }

    frameAspects() {
        const generator = linkedGenerators(this.node)[0];
        const output = this.outputSize(generator);
        const box = el("div", "h3e-aspects");
        let offered = false;
        for (const [slot, label] of FRAMES) {
            const value = getValue(this.node, slot);
            const size = value && mediaSize(value, "image", () => this.renderSoon());
            if (!size) continue;
            const orientation = size.w > size.h ? "横图" : size.w < size.h ? "竖图" : "方图";
            const line = el("div", "h3e-aspect");
            if (!output) {
                line.textContent = `${label} ${size.w}×${size.h}（${orientation}）`;
            } else if (output.kind === "external") {
                line.classList.add("h3e-bad");
                line.textContent = `${label} ${size.w}×${size.h}（${orientation}）。宽高由连接的「${output.source?.title || "其他节点"}」决定，`
                    + `比例不同时会居中裁切成输出比例`;
            } else if (Math.abs(Math.log((size.w / size.h) / (output.w / output.h))) > 0.05) {
                line.classList.add("h3e-bad");
                const from = output.kind === "selector" ? "（分辨率选择器）" : "";
                // with a first frame, only it may reshape the output (switching to the last frame's
                // ratio would just break the first frame)
                const skip = offered || (slot === "last_frame" && getValue(this.node, "first_frame"));
                const button = skip ? null : this.fixButton(label, size, output, generator);
                line.append(el("span", "", `⚠ ${label} ${size.w}×${size.h}（${orientation}）和输出 ${output.w}×${output.h}${from} 比例不同：`
                    + "输出保持你设的尺寸，图片居中裁切，变暗的部分会被裁掉。" + (button ? "想保留整张图可以" : "")));
                if (button) {
                    offered = true;
                    line.append(button);
                }
            } else {
                line.classList.add("h3e-good");
                line.textContent = `✓ ${label} ${size.w}×${size.h} 和输出 ${output.w}×${output.h} 比例一致`;
            }
            box.append(line);
        }
        return box.childElementCount ? box : null;
    }

    lockAudioSection() {
        const value = getValue(this.node, AUDIOS[0]);
        const section = this.section("锁定音频", value ? "按它对口型，最终输出这段原声" : "可选：不放就由 H3 自动配音");
        section.append(value
            ? this.audioItem(AUDIOS, 0, value, null)
            : this.addCard("audio", "添加音频（也可以是带声音的视频）", "h3e-add-row", false,
                (f) => this.putInList(AUDIOS, 0, f)));
        return section;
    }

    refImagesSection() {
        const refs = this.list(REFS);
        const section = this.section(`参考图 ${refs.length}/${LIMIT.image}`, "提示词里写 <Picture N>；拖动调整顺序");
        const ratio = cellRatio(refs.map((value) => ratioOf(mediaSize(value, "image", () => this.renderSoon()))), 1);
        const items = refs.map((value, i) => {
            const card = this.imageCard(value, "", this.tag(`<Picture ${i + 1}>`, "h3e-badge", `图${i + 1}`),
                (f) => this.putInList(REFS, i, f), () => this.removeFromList(REFS, i), { names: REFS, index: i });
            card.style.aspectRatio = String(ratio);
            return card;
        });
        const add = (label, shape) => this.addCard("image", label, shape, true, (f) => this.putInList(REFS, refs.length, f),
            this.slotTake(REFS, refs.length - 1));
        let addRow = null;
        if (refs.length < LIMIT.image) {
            if (refs.length % 3) {
                const card = add("添加", "");
                card.style.aspectRatio = String(ratio);
                items.push(card);
            } else {
                // a lone "add" card gets a slim full-width row instead of a big empty tile
                addRow = refs.length
                    ? add(`继续添加（还能加 ${LIMIT.image - refs.length} 张）`, "h3e-add-row")
                    : add(`添加参考图（可多选，最多 ${LIMIT.image} 张）`, "h3e-add-row h3e-add-tall");
            }
        }
        if (items.length) section.append(grid(3, items));
        if (addRow) section.append(addRow);
        return section;
    }

    videoTracks(videos) {
        // <Audio j> numbering in H3: video soundtracks first, then standalone audio
        let next = 1;
        return videos.map((name) => {
            const info = mediaInfo(name, () => this.renderSoon());
            if (!info) return { info: null, audioTag: null };
            return { info, audioTag: info.has_audio ? next++ : null };
        });
    }

    refVideosSection(tracks) {
        const videos = this.list(VIDEOS);
        const section = this.section(`参考视频 ${videos.length}/${LIMIT.video}`, `提示词里写 <Video N>；最多读 ${VIDEO_READ_SECONDS} 秒`);
        // the browser knows rotated phone videos; the server probe covers codecs the browser can't play
        const ratio = cellRatio(videos.map((value, i) => ratioOf(mediaSize(value, "video", () => this.renderSoon()))
            || ratioOf(tracks[i].info && { w: tracks[i].info.width, h: tracks[i].info.height })), 16 / 9);
        const items = videos.map((value, i) => {
            const info = tracks[i].info;
            const item = el("div", "h3e-vitem");
            const card = el("div", "h3e-card h3e-filled");
            card.style.aspectRatio = String(ratio);
            const video = el("video");
            video.src = `${viewUrl(value)}#t=0.1`;  // show a frame instead of a black box
            video.muted = true;
            video.preload = "metadata";
            video.loop = true;
            const play = el("button", "h3e-play", "▶");
            play.title = "预览";
            play.addEventListener("click", (e) => {
                e.stopPropagation();
                if (video.paused) {
                    video.play();
                    play.textContent = "❚❚";
                } else {
                    video.pause();
                    play.textContent = "▶";
                }
            });
            card.title = videos.length > 1 ? `${value}\n点击替换，拖到别的视频上调整顺序` : `${value}\n点击替换`;
            card.append(video, play, this.removeButton(() => this.removeFromList(VIDEOS, i)));
            card.addEventListener("click", async () => this.putInList(VIDEOS, i, await pickFiles("video", false)));
            this.dropTarget(card, "video", (f) => this.putInList(VIDEOS, i, f), this.slotTake(VIDEOS, i));
            this.movable(card, { names: VIDEOS, index: i }, item);

            const caption = el("div", "h3e-caption");
            caption.append(this.tag(`<Video ${i + 1}>`, "h3e-chip", `视频${i + 1}`));
            const { audioTag } = tracks[i];
            if (info) {
                const long = info.duration > VIDEO_READ_SECONDS;
                const length = el("span", long ? "h3e-warn" : "", formatSeconds(info.duration));
                if (long) length.title = `超过 ${VIDEO_READ_SECONDS} 秒，只读取前 ${VIDEO_READ_SECONDS} 秒`;
                caption.append(length);
                caption.append(audioTag ? this.tag(`<Audio ${audioTag}>`, "h3e-chip", `音频${audioTag}`) : el("span", "", "无声"));
            }
            item.append(card, caption);
            return item;
        });
        const add = (label, shape) => this.addCard("video", label, shape, true, (f) => this.putInList(VIDEOS, videos.length, f),
            this.slotTake(VIDEOS, videos.length - 1));
        if (items.length) {
            if (videos.length < LIMIT.video) {
                const card = add("添加", "");
                card.style.aspectRatio = String(ratio);
                items.push(card);
            }
            section.append(grid(3, items));
        } else {
            section.append(add(`添加参考视频（可多选，最多 ${LIMIT.video} 段）`, "h3e-add-row h3e-add-tall"));
        }
        return section;
    }

    audioItem(names, index, value, tagNumber, reorder = false) {
        const box = el("div", "h3e-audio");
        const line = el("div", "h3e-line");
        line.append(el("span", "h3e-name", `🎵 ${value}`));
        const info = mediaInfo(value, () => this.renderSoon());
        if (info?.duration) line.append(el("span", "h3e-chip", formatSeconds(info.duration)));
        if (tagNumber) line.append(this.tag(`<Audio ${tagNumber}>`, "h3e-chip"));
        const player = el("audio");
        player.controls = true;
        player.preload = "metadata";
        player.src = viewUrl(value);
        box.append(line, player, this.removeButton(() => this.removeFromList(names, index)));
        this.dropTarget(box, "audio", (f) => this.putInList(names, index, f), reorder ? this.slotTake(names, index) : null);
        if (reorder) {
            line.title = "拖到别的音频上调整顺序";
            this.movable(line, { names, index }, box);
        }
        return box;
    }

    refAudiosSection(tracks) {
        const audios = this.list(AUDIOS);
        const offset = tracks.filter((t) => t.audioTag).length;
        const known = tracks.every((t) => t.info);
        const section = this.section(`参考音频 ${audios.length}/${LIMIT.audio}`, "提示词里写 <Audio N>（视频音轨排在前面）");
        audios.forEach((value, i) => section.append(this.audioItem(AUDIOS, i, value, known ? offset + i + 1 : null, true)));
        if (audios.length < LIMIT.audio) {
            section.append(this.addCard("audio", audios.length ? "添加音频" : "添加参考音频（可多选）", "h3e-add-row", true,
                (f) => this.putInList(AUDIOS, audios.length, f)));
        }
        return section;
    }

    hiddenNote(mode) {
        const parts = [];
        if (mode === "image") {
            const refs = this.list(REFS).length;
            const videos = this.list(VIDEOS).length;
            const extraAudio = Math.max(0, this.list(AUDIOS).length - 1);
            if (refs) parts.push(`${refs} 张参考图`);
            if (videos) parts.push(`${videos} 段参考视频`);
            if (extraAudio) parts.push(`${extraAudio} 段参考音频`);
            return parts.length ? `已隐藏参考模式素材：${parts.join("、")}（切到参考模式可见，图文模式不使用）` : "";
        }
        const frames = FRAMES.filter(([slot]) => getValue(this.node, slot)).map(([, label]) => label);
        return frames.length ? `已隐藏图文模式素材：${frames.join("、")}（切到图文模式可见，参考模式不使用）` : "";
    }

    copy(text) {
        const done = () => this.toast(`已复制 ${text}`);
        try {
            navigator.clipboard.writeText(text).then(done, () => this.toast(text));
        } catch {
            this.toast(text);
        }
    }

    toast(text, ms = 1500) {
        this.toastEl.textContent = text;
        this.toastEl.classList.add("h3e-show");
        clearTimeout(this.toastTimer);
        this.toastTimer = setTimeout(() => this.toastEl.classList.remove("h3e-show"), ms);
    }

    renderSoon() {
        if (this.renderTimer) return;
        // media sizes arrive one by one; rebuild once for a burst of them
        this.renderTimer = setTimeout(() => {
            this.renderTimer = null;
            this.render();
        }, 16);
    }

    // Follow the node's own width. Some frontend versions give the DOM layer a wider box
    // than the node draws, which made the panel spill past the node's right edge.
    syncWidth() {
        const width = this.node.size?.[0];
        const margin = this.widget?.margin ?? 10;
        if (width > 0) this.root.style.width = `min(100%, ${Math.max(120, Math.round(width - 2 * margin))}px)`;
    }

    render() {
        this.syncWidth();
        const sheet = this.sheet();
        this.sheetShown = sheet !== undefined;
        if (this.sheetShown) {
            this.renderSheet(sheet);
            return;
        }
        this.clearUnplaced();
        this.guessed.clear();
        this.spare = [];
        const mode = this.mode();
        const inner = this.inner;
        inner.replaceChildren();

        const bar = el("div", "h3e-modebar");
        const pill = el("span", `h3e-pill${mode === "reference" ? " h3e-ref" : mode ? "" : " h3e-all"}`,
            mode === "reference" ? "参考模式" : mode === "image" ? "图文模式" : "全部素材");
        bar.append(pill, el("span", "", mode
            ? "跟随「H3 一键生成」的模式，只显示这个模式用得到的素材"
            : "还没连接「H3 一键生成」，先显示全部素材"));
        inner.append(bar);

        if (mode !== "reference") {
            inner.append(this.framesSection());
            if (mode === "image") inner.append(this.lockAudioSection());
        }
        if (mode !== "image") {
            const tracks = this.videoTracks(this.list(VIDEOS));
            inner.append(this.refImagesSection(), this.refVideosSection(tracks), this.refAudiosSection(tracks));
        }
        if (mode) {
            const note = this.hiddenNote(mode);
            if (note) inner.append(el("div", "h3e-note", note));
        }

        const clip = this.clipNote();
        if (clip) inner.append(clip);
        if (mode) inner.append(this.importRow(), this.aiRow());
        const foot = el("div", "h3e-foot");
        const clear = el("button", "h3e-btn", "清空全部");
        clear.addEventListener("click", () => {
            for (const name of ALL_SLOTS) setValue(this.node, name, null);
            this.render();
        });
        foot.append(this.toastEl, clear);
        inner.append(foot);
        this.fit();
    }

    contentHeight() {
        // the canvas gives the DOM box (layout height - 2 * margin)
        const measured = this.inner.offsetHeight;
        const margin = this.widget?.margin ?? 10;
        return measured > 40 ? measured + 2 * margin + 2 : 420;
    }

    fit() {
        if (this.fitPending) return;
        this.fitPending = true;
        // two frames: let the DOM widget pick up the node width before measuring
        requestAnimationFrame(() => requestAnimationFrame(() => {
            this.fitPending = false;
            const node = this.node;
            if (app.canvas?.resizing_node === node) {
                // The canvas re-applies its drag rectangle on every mouse move; fitting now would
                // fight it and make the bottom of the node jump. It already keeps the node at least
                // computeSize() tall, so just fit once the mouse is released.
                this.fitAfterResize();
                return;
            }
            const want = node.computeSize?.();
            if (want && node.size && Math.abs(node.size[1] - want[1]) > 2) {
                node.setSize([node.size[0], want[1]]);
            }
            node.setDirtyCanvas?.(true, true);
        }));
    }

    fitAfterResize() {
        if (this.resizeWait) return;
        this.resizeWait = true;
        const wait = () => {
            if (app.canvas?.resizing_node === this.node) {
                requestAnimationFrame(wait);
                return;
            }
            this.resizeWait = false;
            this.fit();
        };
        requestAnimationFrame(wait);
    }

    watchSize() {
        if (typeof ResizeObserver === "undefined") return;
        this.observer = new ResizeObserver(() => this.fit());
        this.observer.observe(this.inner);
    }
}

// With the learned upscaler wired in, the upscale-method choice no longer applies to the
// low-res -> full-res handoff; say so on the widget itself.
function markUpscaleMethod(generator) {
    const widget = findWidget(generator, "upscale_method");
    if (!widget) return;
    widget.__h3eLabel ??= (widget.label || "放大方式").replace(/（已改用学习式upscaler）$/, "");
    const linked = generator.inputs?.find((i) => i.name === "learned_upscaler")?.link != null;
    widget.label = linked ? `${widget.__h3eLabel}（已改用学习式upscaler）` : widget.__h3eLabel;
    generator.setDirtyCanvas?.(true, true);
}

function refreshLoaders(generator) {
    for (const loader of loadersFeeding(generator)) loader.__h3ePanel.render();
}

// the prompt changes on every keystroke: wait for a pause
function refreshLoadersSoon(generator) {
    clearTimeout(generator.__h3eRefresh);
    generator.__h3eRefresh = setTimeout(() => refreshLoaders(generator), 300);
}

// Which generator a text file dropped on the page is meant for: the one it was dropped on
// (its prompt box, its node in either renderer), else the only one in the graph.
function generatorAt(e) {
    const generators = (app.graph?._nodes || []).filter((node) => (node.comfyClass || node.type) === GENERATOR
        && !promptLinked(node));
    const target = e.target;
    const boxed = generators.find((node) => {
        const widget = findWidget(node, "prompt");
        return (widget?.element ?? widget?.inputEl)?.contains?.(target);
    });
    if (boxed) return { generator: boxed, direct: true };
    const id = target.closest?.("[data-node-id]")?.dataset.nodeId;
    let under = id != null && generators.find((node) => String(node.id) === id);
    if (!under && target === app.canvas?.canvas) {
        const [x, y] = app.canvas.convertEventToCanvasOffset(e);
        under = generators.find((node) => node === app.graph.getNodeOnPos(x, y));
    }
    if (under) return { generator: under, direct: true };
    return generators.length === 1 ? { generator: generators[0], direct: false } : null;
}

const warn = (detail) => app.extensionManager?.toast?.add({ severity: "warn", summary: "H3 Easy", life: 6000, detail });

// A picture copied in a chat page ("复制图片") and pasted while the mouse is over a card of a shot
// list goes to that card under the name the list asks for: no download, no file to rename. Over
// the rest of a panel it is taken like a dropped file. Anywhere else ComfyUI keeps its own paste.
document.addEventListener("paste", (e) => {
    const files = Array.from(e.clipboardData?.files || []).filter((file) => kindOf(file) !== "other");
    if (!files.length) return;
    const under = Array.from(document.querySelectorAll(":hover")).pop();
    const panel = under?.closest?.(".h3e-panel")?.__h3ePanel;
    if (!panel) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    panel.pasteFiles(files, under.closest("[data-h3e-row]")?.dataset.h3eRow);
}, true);

// A shot list file (.md / .txt) dropped anywhere on the page goes into the generator's prompt, and
// so does a folder: its shot list, with the pictures next to it handed to the media panel.
// ComfyUI itself can only answer such a drop with "no workflow found". Panels take their own drops.
document.addEventListener("dragover", (e) => {
    if (e.dataTransfer?.types?.includes("Files") && !e.target.closest?.(".h3e-panel") && generatorAt(e)) e.preventDefault();
}, true);
document.addEventListener("drop", (e) => {
    if (e.target.closest?.(".h3e-panel")) return;
    if (!dropsFolder(e) && !Array.from(e.dataTransfer?.files || []).some(isSheetFile)) return;
    const found = generatorAt(e);
    if (!found) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    droppedFiles(e).then(async (files) => {
        const sheet = await findSheet(files);
        const lone = !sheet && files.length === 1 && isSheetFile(files[0]) ? files[0] : null;
        const media = files.filter((file) => kindOf(file) !== "other");
        // away from the node, only a real shot list is taken: a stray text file must not wipe the prompt
        if (lone && !found.direct) {
            warn(`${lone.name} 里没有读到出片清单（要有 SHOT 01 这样的镜头卡）。想把它当普通提示词用，就拖到「H3 一键生成」节点上。`);
            return;
        }
        if (!sheet && !lone && !media.length) {
            warn("拖进来的文件夹里没有出片清单（.md / .txt），也没有图片、音频、视频。");
            return;
        }
        const panel = loadersFeeding(found.generator)[0]?.__h3ePanel;
        if (panel) {
            panel.takeFiles(files, found.direct);
            return;
        }
        if (media.length) warn("「H3 一键生成」没有连「H3 素材加载器」，图片没有导入：连上以后再拖一次。");
        if (!sheet && !lone) return;
        setPrompt(found.generator, sheet ? sheet.text : await lone.text());
        refreshLoaders(found.generator);
    });
}, true);

app.registerExtension({
    name: "H3Easy.MediaLoader",
    nodeCreated(node) {
        const type = node.comfyClass || node.type;
        if (type === GENERATOR && !node.__h3eWatch) {
            // re-render the connected panel when the mode, the prompt or the media link changes
            node.__h3eWatch = true;
            for (const name of ["mode", "width", "height", "prompt", "segments", "segment_seconds"]) {
                const widget = findWidget(node, name);
                if (!widget) continue;
                const callback = widget.callback;
                widget.callback = function (...args) {
                    const result = callback?.apply(this, args);
                    if (name === "prompt") refreshLoadersSoon(node);
                    else queueMicrotask(() => refreshLoaders(node));
                    return result;
                };
            }
            const connections = node.onConnectionsChange;
            node.onConnectionsChange = function (...args) {
                const result = connections?.apply(this, args);
                queueMicrotask(() => {
                    markUpscaleMethod(node);
                    refreshLoaders(node);
                    for (const loader of node.graph?._nodes || []) if (loader.__h3ePanel) loader.__h3ePanel.render();
                });
                return result;
            };
            const configure = node.onConfigure;
            node.onConfigure = function (...args) {
                const result = configure?.apply(this, args);
                setTimeout(() => markUpscaleMethod(node), 0);  // links are restored after the node
                return result;
            };
            markUpscaleMethod(node);
            return;
        }
        if (type === "ResolutionSelector" && !node.__h3eWatch) {
            node.__h3eWatch = true;
            for (const widget of node.widgets || []) {
                const callback = widget.callback;
                widget.callback = function (...args) {
                    const result = callback?.apply(this, args);
                    queueMicrotask(() => {
                        for (const other of node.graph?._nodes || []) if (other.__h3ePanel) other.__h3ePanel.render();
                    });
                    return result;
                };
            }
            return;
        }
        if (type !== LOADER || node.__h3ePanel) return;
        ensureStyle();
        for (const name of [...ALL_SLOTS, CLIP_SECONDS]) hideWidget(findWidget(node, name));
        const panel = new MediaPanel(node);
        node.__h3ePanel = panel;
        const widget = node.addDOMWidget("media_panel", "h3easy_media_panel", panel.root, {
            serialize: false,
            hideOnZoom: false,
            getMinHeight: () => panel.contentHeight(),
            getMaxHeight: () => panel.contentHeight(),
        });
        widget.serialize = false;
        panel.widget = widget;
        // the number is read again right before a run is queued, whatever was changed last
        const clip = findWidget(node, CLIP_SECONDS);
        if (clip) {
            clip.beforeQueued = () => panel.syncClip();
            // ComfyUI awaits widget serialization; beforeQueued itself does not await requests.
            clip.serializeValue = async () => {
                const generator = linkedGenerators(node)[0];
                if (generator) clip.value = await clipSecondsForQueue(generator, clip.value);
                return clip.value;
            };
        }
        const configure = node.onConfigure;
        node.onConfigure = function (...args) {
            const result = configure?.apply(this, args);
            // links are restored after the node itself; render once the graph has settled
            setTimeout(() => panel.render(), 0);
            return result;
        };
        const connections = node.onConnectionsChange;
        node.onConnectionsChange = function (...args) {
            const result = connections?.apply(this, args);
            queueMicrotask(() => panel.render());
            return result;
        };
        const resize = node.onResize;
        node.onResize = function (...args) {
            const result = resize?.apply(this, args);
            panel.syncWidth();
            panel.fit();
            return result;
        };
        const removed = node.onRemoved;
        node.onRemoved = function (...args) {
            panel.observer?.disconnect();
            return removed?.apply(this, args);
        };
        // the canvas never lets a resize go below computeSize(); keep room for two frame cards
        const computeSize = node.computeSize;
        node.computeSize = function (...args) {
            const size = computeSize.apply(this, args);
            if (size) size[0] = Math.max(size[0], MIN_WIDTH);
            return size;
        };
        panel.watchSize();
        panel.render();
        node.setSize([Math.max(node.size?.[0] || 0, 420), node.computeSize()[1]]);
    },
});
