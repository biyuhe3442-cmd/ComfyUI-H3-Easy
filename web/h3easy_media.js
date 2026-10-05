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
.h3e-panel{box-sizing:border-box;width:100%;font:12px/1.4 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:var(--input-text,#ddd);user-select:none}
.h3e-inner{display:flex;flex-direction:column;gap:10px;padding:4px 8px 8px}
.h3e-modebar{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--descrip-text,#999)}
.h3e-pill{padding:1px 8px;border-radius:10px;background:#2b5a8a;color:#fff;font-weight:600}
.h3e-pill.h3e-ref{background:#6b3f8a}
.h3e-pill.h3e-all{background:#555}
.h3e-section{display:flex;flex-direction:column;gap:6px}
.h3e-head{display:flex;align-items:baseline;gap:8px}
.h3e-title{font-weight:600;font-size:13px;white-space:nowrap;flex-shrink:0}
.h3e-hint{color:var(--descrip-text,#999);font-size:11px}
.h3e-row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.h3e-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.h3e-card{position:relative;border:1px dashed var(--border-color,#555);border-radius:8px;background:var(--comfy-input-bg,#222);overflow:hidden;cursor:pointer;
  display:flex;align-items:center;justify-content:center;color:var(--descrip-text,#999);transition:border-color .15s,background .15s}
.h3e-card:hover,.h3e-over{border-color:#4a9eff!important;background:rgba(74,158,255,.08)}
.h3e-filled{border-style:solid}
.h3e-frame{aspect-ratio:16/10}
.h3e-square{aspect-ratio:1/1}
.h3e-wide{aspect-ratio:16/10}
.h3e-card img,.h3e-card video{width:100%;height:100%;object-fit:cover;display:block;pointer-events:none}
.h3e-empty{display:flex;flex-direction:column;align-items:center;gap:2px;text-align:center;padding:4px}
.h3e-plus{font-size:20px;line-height:1;opacity:.8}
.h3e-add-row{min-height:38px;flex-direction:row;gap:6px}
.h3e-add-row .h3e-plus{font-size:16px}
.h3e-badge{position:absolute;left:4px;bottom:4px;padding:1px 6px;border-radius:6px;background:rgba(0,0,0,.72);color:#fff;font-size:11px;max-width:calc(100% - 16px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.h3e-tag{cursor:copy}
.h3e-tag:hover{background:#2b5a8a}
.h3e-warn{color:#f0b35a}
.h3e-vitem{display:flex;flex-direction:column;gap:3px;min-width:0}
.h3e-caption{display:flex;flex-wrap:wrap;gap:3px;align-items:center;font-size:10px;color:var(--descrip-text,#aaa)}
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
    widget.hidden = true;
    widget.options ||= {};
    widget.options.hidden = true;
    widget.type = "converted-widget";
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

    tag(text, className = "h3e-badge") {
        const badge = el("span", `${className} h3e-tag`, text);
        badge.title = "点击复制，粘贴到提示词里";
        badge.addEventListener("click", (e) => {
            e.stopPropagation();
            this.copy(text);
        });
        return badge;
    }

    addCard(kind, label, shape, multiple, onFiles) {
        const card = el("div", `h3e-card ${shape}`);
        const empty = el("div", "h3e-empty");
        empty.append(el("div", "h3e-plus", "+"), el("div", "", label));
        card.append(empty);
        card.title = "点击选择文件，或把文件拖到这里";
        card.addEventListener("click", async () => onFiles(await pickFiles(kind, multiple)));
        this.dropTarget(card, kind, onFiles);
        return card;
    }

    imageCard(value, shape, badge, onFiles, onRemove) {
        const card = el("div", `h3e-card h3e-filled ${shape}`);
        const img = el("img");
        img.src = viewUrl(value);
        img.alt = typeof badge === "string" ? badge : badge.textContent;
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
        const row = el("div", "h3e-row");
        for (const [slot, label] of FRAMES) {
            const value = getValue(this.node, slot);
            row.append(value
                ? this.imageCard(value, "h3e-frame", label, (f) => this.setSingle(slot, f), () => {
                    setValue(this.node, slot, null);
                    this.render();
                })
                : this.addCard("image", label, "h3e-frame", false, (f) => this.setSingle(slot, f)));
        }
        section.append(row);
        return section;
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
        const grid = el("div", "h3e-grid");
        refs.forEach((value, i) => {
            grid.append(this.imageCard(value, "h3e-square", this.tag(`<Picture ${i + 1}>`),
                (f) => this.putInList(REFS, i, f), () => this.removeFromList(REFS, i)));
        });
        if (refs.length < LIMIT.image) {
            grid.append(this.addCard("image", refs.length ? "添加" : "添加参考图（可多选）", "h3e-square", true,
                (f) => this.putInList(REFS, refs.length, f)));
        }
        section.append(grid);
        return section;
    }

    videoTracks(videos) {
        // <Audio j> numbering in H3: video soundtracks first, then standalone audio
        let next = 1;
        return videos.map((name) => {
            const info = mediaInfo(name, () => this.render());
            if (!info) return { info: null, audioTag: null };
            return { info, audioTag: info.has_audio ? next++ : null };
        });
    }

    refVideosSection(tracks) {
        const videos = this.list(VIDEOS);
        const section = this.section(`参考视频 ${videos.length}/${LIMIT.video}`, `提示词里写 <Video N>；最多读 ${VIDEO_READ_SECONDS} 秒`);
        const grid = el("div", "h3e-grid");
        videos.forEach((value, i) => {
            const item = el("div", "h3e-vitem");
            const card = el("div", "h3e-card h3e-filled h3e-wide");
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
            caption.append(this.tag(`<Video ${i + 1}>`, "h3e-chip"));
            const { info, audioTag } = tracks[i];
            if (info) {
                const long = info.duration > VIDEO_READ_SECONDS;
                const length = el("span", long ? "h3e-warn" : "", formatSeconds(info.duration));
                if (long) length.title = `超过 ${VIDEO_READ_SECONDS} 秒，只读取前 ${VIDEO_READ_SECONDS} 秒`;
                caption.append(length);
                caption.append(audioTag ? this.tag(`<Audio ${audioTag}>`, "h3e-chip") : el("span", "", "无声"));
            }
            item.append(card, caption);
            grid.append(item);
        });
        if (videos.length < LIMIT.video) {
            grid.append(this.addCard("video", videos.length ? "添加" : "添加参考视频", "h3e-wide", true,
                (f) => this.putInList(VIDEOS, videos.length, f)));
        }
        section.append(grid);
        return section;
    }

    audioItem(names, index, value, tagNumber) {
        const box = el("div", "h3e-audio");
        const line = el("div", "h3e-line");
        line.append(el("span", "h3e-name", `🎵 ${value}`));
        const info = mediaInfo(value, () => this.render());
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

    toast(text) {
        if (!this.toastEl) return;
        this.toastEl.textContent = text;
        this.toastEl.classList.add("h3e-show");
        clearTimeout(this.toastTimer);
        this.toastTimer = setTimeout(() => this.toastEl.classList.remove("h3e-show"), 1500);
    }

    render() {
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
        this.toastEl = el("span", "h3e-toast");
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
        const measured = this.inner.offsetHeight;
        return measured > 40 ? measured + 4 : 420;
    }

    fit() {
        requestAnimationFrame(() => {
            const node = this.node;
            const want = node.computeSize?.();
            if (want && node.size && Math.abs(node.size[1] - want[1]) > 2) {
                node.setSize([node.size[0], want[1]]);
            }
            node.setDirtyCanvas?.(true, true);
        });
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
            const modeWidget = findWidget(node, "mode");
            if (modeWidget) {
                const callback = modeWidget.callback;
                modeWidget.callback = function (...args) {
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
        panel.render();
        node.setSize([Math.max(node.size?.[0] || 0, 420), node.computeSize()[1]]);
    },
});
