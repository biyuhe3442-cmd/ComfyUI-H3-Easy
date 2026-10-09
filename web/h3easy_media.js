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
const MIN_WIDTH = 360;

const FRAMES = [["first_frame", "首帧"], ["last_frame", "尾帧"]];
const REFS = Array.from({ length: LIMIT.image }, (_, i) => `ref_image_${i + 1}`);
const VIDEOS = Array.from({ length: LIMIT.video }, (_, i) => `video_${i + 1}`);
const AUDIOS = Array.from({ length: LIMIT.audio }, (_, i) => `audio_${i + 1}`);
const ALL_SLOTS = [...FRAMES.map((f) => f[0]), ...REFS, ...AUDIOS, ...VIDEOS];
const ACCEPT = {
    image: "image/*,.png,.jpg,.jpeg,.webp,.bmp",
    audio: "audio/*,video/*,.wav,.mp3,.flac,.ogg,.m4a,.aac,.mp4,.mov",
    video: "video/*,.mp4,.mov,.webm,.mkv,.avi",
    any: "image/*,audio/*,video/*",
};
const DROP_KINDS = { image: ["image"], audio: ["audio", "video"], video: ["video"], any: ["image", "audio", "video"] };

const STYLE = `
.h3e-panel{box-sizing:border-box;width:100%;max-width:100%;overflow:hidden;font:12px/1.4 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:var(--input-text,#ddd);user-select:none}
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

function viewUrl(name) {
    const [subfolder, filename] = splitName(name);
    return api.apiURL(`/view?${new URLSearchParams({ filename, subfolder, type: "input" })}`);
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
async function upload(file, overwrite = false) {
    const body = new FormData();
    body.append("image", file);
    if (overwrite) body.append("overwrite", "true");
    const response = await api.fetchApi("/upload/image", { method: "POST", body });
    if (response.status !== 200) throw new Error(`${response.status} ${response.statusText}`);
    const data = await response.json();
    return data.subfolder ? `${data.subfolder}/${data.name}` : data.name;
}

function pickFiles(kind, multiple) {
    return new Promise((resolve) => {
        const input = el("input");
        input.type = "file";
        input.accept = ACCEPT[kind];
        input.multiple = !!multiple;
        input.style.display = "none";
        input.onchange = () => {
            resolve(Array.from(input.files || []));
            input.remove();
        };
        document.body.appendChild(input);
        input.click();
    });
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

const isSheetFile = (file) => /\.(md|markdown|txt)$/i.test(file.name);
const MEDIA_EXT = /\.(png|jpe?g|webp|bmp|gif|wav|mp3|flac|ogg|m4a|aac|mp4|mov|webm|mkv|avi)$/i;
const promptLinked = (generator) => generator.inputs?.find((i) => i.name === "prompt")?.link != null;

// What a user hands to any chat AI to get a shot list back: the single-file NB-H3-Director rules
// (shot_list_template.md, kept word for word) plus a closing note that this plugin reads the reply.
// Loaded up front so the copy button can write to the clipboard right inside the click.
const AI_TEMPLATE_NOTE = `

---

## 我的出片环境和输出要求（以这一段为准，和前面冲突时听这里的）

我用的是 ComfyUI-H3-Easy 插件，它会直接读取你输出的清单。

**怎么输出**

- 不管是一个镜头还是多个镜头，都输出一份完整的出片清单，格式照第 16 节：开头是画幅和素材表，然后每个镜头一张卡，每张卡都有「接上一镜:」，References 每行用反引号写文件名。
- 整份清单放在一个代码框里，我要一键复制。清单里面不要再套代码框：「H3 Prompt:」下面直接写提示词，每张卡以「注意事项：」结尾。
- 代码框外面不要写任何话：不解释，不分析，不问我要不要继续。
- 不要把每个镜头的提示词分开给我，也不要只给提示词不给卡片上的其他字段。

**怎么对待我给的内容**

- 我给了的剧情、台词、人物关系、镜头数、时长，原样照做，不改写、不加戏、不删减。
- 我没给的才由你补，补了什么写在清单开头的「我替你定的」里。
- 我没说文件名时，你给每张图起一个文件名（例如「沈砚.png」），写进素材表。

读完以上全部规则后，只回复下面这段话，然后等我发素材：

规则收到。请把参考图发给我，并告诉我：
剧情：（发生了什么；有台词就写上）
总时长：（比如 20 秒）
每张图是什么：（按发图顺序，比如 图1 男主沈砚，图2 讨债的老妇，图3 漏雨的草屋）
`;
let aiTemplate = "";
fetch(new URL("./shot_list_template.md", import.meta.url)).then((r) => (r.ok ? r.text() : "")).then((text) => {
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
        this.inner = el("div", "h3e-inner");
        this.root.append(this.inner);
        for (const type of ["dragenter", "dragover", "dragleave", "drop"]) {
            // keep file drops away from ComfyUI's canvas handler (it would open them as workflows)
            this.root.addEventListener(type, (e) => {
                e.preventDefault();
                e.stopPropagation();
            });
        }
        this.root.addEventListener("drop", (e) => {
            const files = Array.from(e.dataTransfer?.files || []);
            const sheet = files.find(isSheetFile);
            if (sheet) this.takeSheet(sheet);
            // cards and list rows take the files dropped on them themselves
            if ((sheet || this.sheetShown) && !e.target.closest?.(".h3e-card, .h3e-file")) this.addSheetFiles(files);
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
        for (const file of files) {
            try {
                names.push(await upload(file, overwrite));
            } catch (error) {
                console.error("[H3 Easy] upload failed", error);
                alert(`上传失败：${file.name}\n${error.message ?? error}`);
            }
        }
        return names;
    }

    // ---------- director shot list ----------
    sheet() {
        const generator = linkedGenerators(this.node)[0];
        const text = generator && !promptLinked(generator) && findWidget(generator, "prompt")?.value;
        return typeof text === "string" ? readSheet(text, () => this.renderSoon()) : undefined;
    }

    // a shot list file dropped on the panel becomes the generator's prompt
    async takeSheet(file) {
        const generator = linkedGenerators(this.node)[0];
        if (!generator || promptLinked(generator)) {
            this.toast(generator ? "提示词是连线进来的，清单要放到连过来的那个节点里" : "先把「素材」连到「H3 一键生成」", 3000);
            return;
        }
        setPrompt(generator, await file.text());
        this.render();
    }

    // files for a shot list only need to be in the input folder; a redone file replaces the old one
    async addSheetFiles(files) {
        const media = files.filter((file) => kindOf(file) !== "other");
        if (!media.length) return;
        await this.uploadAll(media, true);
        SHEETS.clear();
        this.render();
    }

    // a file given to one row of the list is stored under the name the list asks for
    async bindSheetFile(wanted, file) {
        if (!file) return;
        const stem = wanted.split(/[\\/]/).pop().replace(MEDIA_EXT, "");
        const extension = (file.name.match(/\.[^.]+$/) || [""])[0];
        await this.uploadAll([new File([file], stem + extension, { type: file.type })], true);
        SHEETS.clear();
        this.render();
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

    // click or drop on one of the list's files to supply it
    bindable(target, row) {
        const kind = row.kind === "picture" ? "image" : row.kind;
        target.title = (row.found ? `${row.wanted}\n用的是 input/${row.found}` : `${row.wanted}\ninput 文件夹里没有这个文件`)
            + "\n点击选文件，或把文件拖到这里：会按这个名字存进去";
        target.addEventListener("click", async () => this.bindSheetFile(row.wanted, (await pickFiles(kind, false))[0]));
        this.dropTarget(target, kind, (files) => this.bindSheetFile(row.wanted, files[0]));
    }

    sheetCard(row, ratio) {
        const card = el("div", `h3e-card ${row.found ? "h3e-filled" : "h3e-missing"}`);
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
            empty.append(el("div", "h3e-plus", "缺"), el("div", "", "点击选择，或拖到这里"));
            card.append(empty);
        }
        card.append(el("span", "h3e-badge", row.wanted), el("span", "h3e-use", `镜头 ${row.shots.join("、")}`));
        this.bindable(card, row);
        return card;
    }

    // "can't write prompts": hand the director rules to a chat AI, paste its shot list back
    aiRow() {
        const row = el("div", "h3e-ai");
        const template = () => {
            if (!aiTemplate) this.toast("模板没读到，刷新页面再试", 3000);
            return aiTemplate && aiTemplate + AI_TEMPLATE_NOTE;
        };
        const copy = el("button", "h3e-fit", "复制 AI 模板");
        copy.title = "把导演规则复制下来，粘贴给豆包、DeepSeek、Kimi、ChatGPT 等任意 AI，再把参考图和剧情发给它";
        copy.addEventListener("click", () => {
            const text = template();
            if (!text) return;
            navigator.clipboard.writeText(text).then(
                () => this.toast("已复制。粘贴给任意 AI，再发参考图和剧情；它嫌太长就点「下载模板」发文件", 6000),
                () => this.toast("浏览器不让复制，点「下载模板」把文件发给 AI", 5000));
        });
        const save = el("button", "h3e-fit", "下载模板");
        save.title = "模板有六万多字，有的 AI 不让粘贴这么长：下载成文件，把文件发给它";
        save.addEventListener("click", () => {
            const text = template();
            if (!text) return;
            const link = el("a");
            link.href = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
            link.download = "H3导演模板.md";
            link.click();
            setTimeout(() => URL.revokeObjectURL(link.href), 1000);
            this.toast("已下载 H3导演模板.md。把这个文件发给 AI，再发参考图和剧情", 6000);
        });
        const paste = el("button", "h3e-fit", "粘贴清单");
        paste.title = "把 AI 回的出片清单复制好，点这里填进「H3 一键生成」的提示词";
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
            const rows = new Map();  // one row per file the list names, however many shots use it
            for (const shot of info.shots) {
                for (const file of shot.files) {
                    const kind = file.tag.slice(1, file.tag.indexOf(" ")).toLowerCase();
                    const key = `${kind}/${file.wanted}`;
                    if (!rows.has(key)) rows.set(key, { ...file, kind, shots: [] });
                    rows.get(key).shots.push(shot.number);
                }
            }
            const missing = [...rows.values()].filter((row) => !row.found).length;
            bar.append(el("span", "", `${info.shots.length} 个镜头，素材 ${rows.size - missing}/${rows.size}`
                + (missing ? "，把缺的拖到面板上" : "，可以运行")));
            for (const problem of info.problems) inner.append(el("div", "h3e-aspect h3e-bad", problem));
            const section = this.section("清单里的素材", "名字对不上，就把文件拖到那张卡片上");
            // pictures and videos as cards, like the ordinary panel; audio as rows
            const visual = [...rows.values()].filter((row) => row.kind !== "audio");
            const ratio = cellRatio(visual.map((row) => row.found
                && ratioOf(mediaSize(row.found, row.kind === "video" ? "video" : "image", () => this.renderSoon()))), 1);
            if (visual.length) section.append(grid(visual.length <= 4 ? 2 : 3, visual.map((row) => this.sheetCard(row, ratio))));
            for (const row of rows.values()) {
                if (row.kind !== "audio") continue;
                const line = el("div", "h3e-file");
                this.bindable(line, row);
                line.append(el("span", `h3e-chip ${row.found ? "h3e-ok" : "h3e-miss"}`, row.found ? "✓" : "缺"),
                    el("span", "h3e-name", `🎵 ${row.wanted}`), el("span", "h3e-hint", `镜头 ${row.shots.join("、")}`));
                section.append(line);
            }
            section.append(this.addCard("any", "把图、音频、视频拖到面板上，或点这里选（可多选）", "h3e-add-row", true,
                (files) => this.addSheetFiles(files)));
            inner.append(section, this.shotsSection(info));
            const own = ALL_SLOTS.filter((name) => getValue(this.node, name)).length;
            if (own) inner.append(el("div", "h3e-note", `面板里原来放的 ${own} 个素材不参与出片清单，提示词换回普通写法后恢复显示`));
        } else {
            bar.append(el("span", "", "正在读取…"));
        }
        inner.append(this.aiRow());
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

    // replace entry ``index`` (or append when index === list length) and append any extra files
    async putInList(names, index, files) {
        const uploaded = await this.uploadAll(files);
        if (!uploaded.length) return;
        const values = this.list(names);
        if (index < values.length) values[index] = uploaded.shift();
        for (const name of uploaded) if (values.length < names.length) values.push(name);
        this.writeList(names, values);
        this.render();
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
    // ``slot`` ({names, index}) also accepts list items dragged here from the same list
    dropTarget(target, kind, onFiles, slot = null) {
        const accepts = () => !moving || (slot && moving.panel === this && moving.names === slot.names);
        target.addEventListener("dragover", (e) => {
            if (!accepts()) return;
            if (moving && e.dataTransfer) e.dataTransfer.dropEffect = "move";
            target.classList.add("h3e-over");
        });
        target.addEventListener("dragleave", () => target.classList.remove("h3e-over"));
        target.addEventListener("drop", (e) => {
            target.classList.remove("h3e-over");
            if (moving) {
                if (accepts()) this.moveInList(slot.names, moving.index, slot.index);
                return;
            }
            const files = Array.from(e.dataTransfer?.files || []).filter((f) => DROP_KINDS[kind].includes(kindOf(f)));
            if (files.length) onFiles(files);
        });
    }

    // let a list item be dragged onto another item of the same list to take its place
    movable(handle, names, index, item = handle) {
        handle.draggable = true;
        handle.classList.add("h3e-grip");
        // keep the node from starting its own drag
        handle.addEventListener("pointerdown", (e) => e.stopPropagation());
        handle.addEventListener("dragstart", (e) => {
            e.stopPropagation();
            moving = { panel: this, names, index };
            if (e.dataTransfer) {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/x-h3e-move", String(index));
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

    addCard(kind, label, shape, multiple, onFiles) {
        const card = el("div", `h3e-card ${shape || ""}`);
        const empty = el("div", "h3e-empty");
        empty.append(el("div", "h3e-plus", "+"), el("div", "", label));
        card.append(empty);
        card.title = "点击选择文件，或把文件拖到这里";
        card.addEventListener("click", async () => onFiles(await pickFiles(kind, multiple)));
        this.dropTarget(card, kind, onFiles);
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
        this.dropTarget(card, "image", onFiles, slot);
        if (slot) this.movable(card, slot.names, slot.index);
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
        const add = (label, shape) => this.addCard("image", label, shape, true, (f) => this.putInList(REFS, refs.length, f));
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
            this.dropTarget(card, "video", (f) => this.putInList(VIDEOS, i, f), { names: VIDEOS, index: i });
            this.movable(card, VIDEOS, i, item);

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
        const add = (label, shape) => this.addCard("video", label, shape, true, (f) => this.putInList(VIDEOS, videos.length, f));
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
        this.dropTarget(box, "audio", (f) => this.putInList(names, index, f), reorder ? { names, index } : null);
        if (reorder) {
            line.title = "拖到别的音频上调整顺序";
            this.movable(line, names, index, box);
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

        if (mode) inner.append(this.aiRow());
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

// A shot list file (.md / .txt) dropped anywhere on the page goes into the generator's prompt.
// ComfyUI itself can only answer such a file with "no workflow found". Panels take their own drops.
document.addEventListener("dragover", (e) => {
    if (e.dataTransfer?.types?.includes("Files") && !e.target.closest?.(".h3e-panel") && generatorAt(e)) e.preventDefault();
}, true);
document.addEventListener("drop", (e) => {
    const sheet = Array.from(e.dataTransfer?.files || []).find(isSheetFile);
    if (!sheet || e.target.closest?.(".h3e-panel")) return;
    const found = generatorAt(e);
    if (!found) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    sheet.text().then((text) => {
        // away from the node, only a real shot list is taken: a stray text file must not wipe the prompt
        if (!found.direct && !SHEET.test(text)) {
            app.extensionManager?.toast?.add({ severity: "warn", summary: "H3 Easy", life: 6000,
                detail: `${sheet.name} 里没有读到出片清单（要有 SHOT 01 这样的镜头卡）。想把它当普通提示词用，就拖到「H3 一键生成」节点上。` });
            return;
        }
        setPrompt(found.generator, text);
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
            for (const name of ["mode", "width", "height", "prompt"]) {
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
        for (const name of ALL_SLOTS) hideWidget(findWidget(node, name));
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
