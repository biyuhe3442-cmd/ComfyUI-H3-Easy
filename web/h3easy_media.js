import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Visual media panel for "H3 素材加载器". The real values live in the node's
// hidden combo widgets, so saving, loading and queueing work as usual.
// The panel follows the mode of the connected "H3 一键生成" and only shows
// what that mode uses: filled items plus one "add" card until the H3 limit.
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
};
const DROP_KINDS = { image: ["image"], audio: ["audio", "video"], video: ["video"] };

const STYLE = `
.h3e-panel{box-sizing:border-box;width:100%;max-width:100%;overflow:hidden;font:12px/1.4 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:var(--input-text,#ddd);user-select:none}
.h3e-inner{display:flex;flex-direction:column;gap:10px;padding:4px 8px 8px;min-width:0}
.h3e-modebar{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--descrip-text,#999)}
.h3e-pill{flex-shrink:0;white-space:nowrap;padding:1px 8px;border-radius:10px;background:#2b5a8a;color:#fff;font-weight:600}
.h3e-pill.h3e-ref{background:#6b3f8a}
.h3e-pill.h3e-all{background:#555}
.h3e-section{display:flex;flex-direction:column;gap:6px;min-width:0}
.h3e-head{display:flex;align-items:baseline;gap:8px}
.h3e-title{font-weight:600;font-size:13px;white-space:nowrap;flex-shrink:0}
.h3e-hint{color:var(--descrip-text,#999);font-size:11px}
.h3e-rows{display:flex;flex-direction:column;gap:6px}
.h3e-jrow{display:flex;gap:6px;align-items:flex-start}
.h3e-jrow>*{min-width:0}
.h3e-card{position:relative;box-sizing:border-box;min-width:0;min-height:0;border:1px dashed var(--border-color,#555);border-radius:8px;background:var(--comfy-input-bg,#222);overflow:hidden;cursor:pointer;
  display:flex;align-items:center;justify-content:center;color:var(--descrip-text,#999);transition:border-color .15s,background .15s}
.h3e-card:hover,.h3e-over{border-color:#4a9eff!important;background:rgba(74,158,255,.08)}
.h3e-filled{border-style:solid}
.h3e-card img,.h3e-card video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#111;display:block;pointer-events:none}
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

async function upload(file) {
    const body = new FormData();
    body.append("image", file);
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

// same as mediaSize, as a promise
function loadSize(name, kind) {
    const known = SIZES.get(name);
    if (known !== undefined) return Promise.resolve(known);
    mediaSize(name, kind, () => {});
    return SIZES.get(name);
}

const clampRatio = (ratio) => Math.min(2.5, Math.max(0.4, ratio));
const ratioOf = (size) => (size && size.w > 0 && size.h > 0 ? clampRatio(size.w / size.h) : null);

// A row where every card keeps its own aspect ratio and all cards share one height
// (flex-grow = ratio). Rows whose ratios add up to less than ``minRatio`` get a spacer
// on the right, so a few portrait images never make the row too tall.
function justifiedRow(items, minRatio) {
    const row = el("div", "h3e-jrow");
    let total = 0;
    for (const { item, ratio } of items) {
        item.style.flex = `${ratio} 1 0`;
        total += ratio;
        row.append(item);
    }
    if (total < minRatio) {
        const spacer = el("div");
        spacer.style.flex = `${minRatio - total} 1 0`;
        row.append(spacer);
    }
    return row;
}

// output size with the image's aspect ratio and about the same pixel area, on H3's 32-pixel grid
function sizeForAspect(image, output) {
    const area = output.w * output.h;
    const ratio = image.w / image.h;
    const snap = (v) => Math.min(2048, Math.max(256, Math.round(v / 32) * 32));
    return { w: snap(Math.sqrt(area * ratio)), h: snap(Math.sqrt(area / ratio)) };
}

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

    async uploadAll(files) {
        const names = [];
        for (const file of files) {
            try {
                names.push(await upload(file));
            } catch (error) {
                console.error("[H3 Easy] upload failed", error);
                alert(`上传失败：${file.name}\n${error.message ?? error}`);
            }
        }
        return names;
    }

    async setSingle(slot, files) {
        const [name] = await this.uploadAll(files.slice(0, 1));
        if (!name) return;
        setValue(this.node, slot, name);
        this.render();
        // the first frame (or a lone last frame) decides the video's shape: match the output to it
        if (slot === "first_frame" || !getValue(this.node, "first_frame")) this.alignOutput(slot);
    }

    async alignOutput(slot) {
        const value = getValue(this.node, slot);
        const size = value && await loadSize(value, "image");
        if (!size || getValue(this.node, slot) !== value || this.mode() !== "image") return;
        const generator = linkedGenerators(this.node)[0];
        const plan = this.aspectPlan(size, this.outputSize(generator), generator);
        if (!plan) return;
        plan.apply();
        const label = FRAMES.find(([name]) => name === slot)[1];
        this.toast(`已按${label}比例把${plan.target}`, 5000);
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

    // ---------- small builders ----------
    dropTarget(target, kind, onFiles) {
        target.addEventListener("dragover", () => target.classList.add("h3e-over"));
        target.addEventListener("dragleave", () => target.classList.remove("h3e-over"));
        target.addEventListener("drop", (e) => {
            target.classList.remove("h3e-over");
            const files = Array.from(e.dataTransfer?.files || []).filter((f) => DROP_KINDS[kind].includes(kindOf(f)));
            if (files.length) onFiles(files);
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

    imageCard(value, shape, badge, onFiles, onRemove) {
        const card = el("div", `h3e-card h3e-filled ${shape || ""}`);
        const img = el("img");
        img.src = viewUrl(value);
        img.alt = typeof badge === "string" ? badge : badge.dataset.text;
        card.title = `${value}\n点击替换`;
        card.append(img, this.removeButton(onRemove), typeof badge === "string" ? el("span", "h3e-badge", badge) : badge);
        card.addEventListener("click", async () => onFiles(await pickFiles("image", false)));
        this.dropTarget(card, "image", onFiles);
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
        const items = FRAMES.map(([slot, label], i) => {
            // a card shows its image's own shape; an empty card copies the other frame, then the output size
            const ratio = ratios[i] || ratios[1 - i] || outputRatio || 16 / 10;
            const card = values[i]
                ? this.imageCard(values[i], "h3e-frame", label, (f) => this.setSingle(slot, f), () => {
                    setValue(this.node, slot, null);
                    this.render();
                })
                : this.addCard("image", label, "h3e-frame", false, (f) => this.setSingle(slot, f));
            card.style.aspectRatio = String(ratio);
            return { item: card, ratio };
        });
        section.append(justifiedRow(items, 1.5));
        const aspects = this.frameAspects();
        if (aspects) section.append(aspects);
        return section;
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
                    + `请确认它的比例和${label}一致，否则${slot === "first_frame" ? "会被拉伸变形" : "会被居中裁切"}`;
            } else if (Math.abs(Math.log((size.w / size.h) / (output.w / output.h))) > 0.05) {
                line.classList.add("h3e-bad");
                const from = output.kind === "selector" ? "（分辨率选择器）" : "";
                line.append(el("span", "", `⚠ ${label} ${size.w}×${size.h}（${orientation}）和输出 ${output.w}×${output.h}${from} 比例不同，`
                    + (slot === "first_frame" ? "会被拉伸变形" : "会被居中裁切")));
                if (!offered) {
                    const button = this.fixButton(label, size, output, generator);
                    if (button) {
                        offered = true;
                        line.append(button);
                    }
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
        const section = this.section(`参考图 ${refs.length}/${LIMIT.image}`, "提示词里写 <Picture N>");
        const items = refs.map((value, i) => {
            const ratio = ratioOf(mediaSize(value, "image", () => this.renderSoon())) || 1;
            const card = this.imageCard(value, "", this.tag(`<Picture ${i + 1}>`, "h3e-badge", `图${i + 1}`),
                (f) => this.putInList(REFS, i, f), () => this.removeFromList(REFS, i));
            card.style.aspectRatio = String(ratio);
            return { item: card, ratio };
        });
        const add = (label, shape) => this.addCard("image", label, shape, true, (f) => this.putInList(REFS, refs.length, f));
        let addRow = null;
        if (refs.length < LIMIT.image) {
            if (refs.length % 3) {
                const card = add("添加", "");
                card.style.aspectRatio = "1";
                items.push({ item: card, ratio: 1 });
            } else {
                // a lone "add" card gets a slim full-width row instead of a big empty tile
                addRow = refs.length
                    ? add(`继续添加（还能加 ${LIMIT.image - refs.length} 张）`, "h3e-add-row")
                    : add(`添加参考图（可多选，最多 ${LIMIT.image} 张）`, "h3e-add-row h3e-add-tall");
            }
        }
        if (items.length) {
            const rows = el("div", "h3e-rows");
            for (let i = 0; i < items.length; i += 3) rows.append(justifiedRow(items.slice(i, i + 3), 2.4));
            section.append(rows);
        }
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
        const items = videos.map((value, i) => {
            // the browser knows rotated phone videos; the server probe covers codecs the browser can't play
            const info = tracks[i].info;
            const ratio = ratioOf(mediaSize(value, "video", () => this.renderSoon()))
                || ratioOf(info && { w: info.width, h: info.height }) || 16 / 9;
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
            card.title = `${value}\n点击替换`;
            card.append(video, play, this.removeButton(() => this.removeFromList(VIDEOS, i)));
            card.addEventListener("click", async () => this.putInList(VIDEOS, i, await pickFiles("video", false)));
            this.dropTarget(card, "video", (f) => this.putInList(VIDEOS, i, f));

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
            return { item, ratio };
        });
        const add = (label, shape) => this.addCard("video", label, shape, true, (f) => this.putInList(VIDEOS, videos.length, f));
        if (items.length) {
            if (videos.length < LIMIT.video) {
                const card = add("添加", "");
                card.style.aspectRatio = "1";
                items.push({ item: card, ratio: 1 });
            }
            section.append(justifiedRow(items, 3.6));
        } else {
            section.append(add(`添加参考视频（可多选，最多 ${LIMIT.video} 段）`, "h3e-add-row h3e-add-tall"));
        }
        return section;
    }

    audioItem(names, index, value, tagNumber) {
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
        this.dropTarget(box, "audio", (f) => this.putInList(names, index, f));
        return box;
    }

    refAudiosSection(tracks) {
        const audios = this.list(AUDIOS);
        const offset = tracks.filter((t) => t.audioTag).length;
        const known = tracks.every((t) => t.info);
        const section = this.section(`参考音频 ${audios.length}/${LIMIT.audio}`, "提示词里写 <Audio N>（视频音轨排在前面）");
        audios.forEach((value, i) => section.append(this.audioItem(AUDIOS, i, value, known ? offset + i + 1 : null)));
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

function refreshLoaders(generator) {
    for (const loader of loadersFeeding(generator)) loader.__h3ePanel.render();
}

app.registerExtension({
    name: "H3Easy.MediaLoader",
    nodeCreated(node) {
        const type = node.comfyClass || node.type;
        if (type === GENERATOR && !node.__h3eWatch) {
            // re-render the connected panel when the mode or the media link changes
            node.__h3eWatch = true;
            for (const name of ["mode", "width", "height"]) {
                const widget = findWidget(node, name);
                if (!widget) continue;
                const callback = widget.callback;
                widget.callback = function (...args) {
                    const result = callback?.apply(this, args);
                    queueMicrotask(() => refreshLoaders(node));
                    return result;
                };
            }
            const connections = node.onConnectionsChange;
            node.onConnectionsChange = function (...args) {
                const result = connections?.apply(this, args);
                queueMicrotask(() => {
                    refreshLoaders(node);
                    for (const loader of node.graph?._nodes || []) if (loader.__h3ePanel) loader.__h3ePanel.render();
                });
                return result;
            };
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
