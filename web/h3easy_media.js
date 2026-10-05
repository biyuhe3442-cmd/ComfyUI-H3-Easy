import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Visual media panel for "H3 素材加载器". The real values live in the node's
// (hidden) combo widgets, so saving, loading and queueing work as usual.
const NODE = "H3EasyMediaLoader";
const NONE = "无";
const REF_COUNT = 9;
const FRAME_SLOTS = [
    ["first_frame", "首帧"],
    ["last_frame", "尾帧"],
];
const REF_SLOTS = Array.from({ length: REF_COUNT }, (_, i) => `ref_image_${i + 1}`);
const ALL_SLOTS = [...FRAME_SLOTS.map((s) => s[0]), ...REF_SLOTS, "audio_file", "video_file"];
const ACCEPT = {
    image: "image/*,.png,.jpg,.jpeg,.webp,.bmp",
    audio: "audio/*,video/*,.wav,.mp3,.flac,.ogg,.m4a,.aac,.mp4,.mov",
    video: "video/*,.mp4,.mov,.webm,.mkv,.avi",
};

const STYLE = `
.h3e-panel{box-sizing:border-box;width:100%;padding:6px 8px 10px;font:12px/1.4 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
  color:var(--input-text,#ddd);display:flex;flex-direction:column;gap:10px;user-select:none}
.h3e-section{display:flex;flex-direction:column;gap:6px}
.h3e-head{display:flex;align-items:baseline;gap:8px}
.h3e-title{font-weight:600;font-size:13px;white-space:nowrap;flex-shrink:0}
.h3e-hint{color:var(--descrip-text,#999);font-size:11px}
.h3e-row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.h3e-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.h3e-card{position:relative;border:1px dashed var(--border-color,#555);border-radius:8px;background:var(--comfy-input-bg,#222);
  overflow:hidden;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--descrip-text,#999);transition:border-color .15s,background .15s}
.h3e-card:hover,.h3e-card.h3e-over{border-color:#4a9eff;background:rgba(74,158,255,.08)}
.h3e-card.h3e-filled{border-style:solid}
.h3e-frame{aspect-ratio:16/10}
.h3e-ref{aspect-ratio:1/1}
.h3e-card img,.h3e-card video{width:100%;height:100%;object-fit:cover;display:block;pointer-events:none}
.h3e-empty{display:flex;flex-direction:column;align-items:center;gap:2px;text-align:center;padding:4px}
.h3e-plus{font-size:22px;line-height:1;opacity:.8}
.h3e-badge{position:absolute;left:4px;bottom:4px;padding:1px 6px;border-radius:6px;background:rgba(0,0,0,.7);color:#fff;font-size:11px}
.h3e-tag{cursor:copy}
.h3e-x{position:absolute;right:4px;top:4px;width:20px;height:20px;border-radius:10px;border:none;background:rgba(0,0,0,.65);
  color:#fff;font-size:13px;line-height:20px;text-align:center;cursor:pointer;padding:0}
.h3e-x:hover{background:#d33}
.h3e-media{position:relative;border:1px solid var(--border-color,#555);border-radius:8px;background:var(--comfy-input-bg,#222);padding:8px;display:flex;flex-direction:column;gap:6px}
.h3e-media .h3e-x{top:6px;right:6px}
.h3e-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:26px}
.h3e-media audio{width:100%;height:32px}
.h3e-media video{width:100%;max-height:170px;border-radius:6px;background:#000}
.h3e-drop{min-height:54px}
.h3e-foot{display:flex;justify-content:space-between;align-items:center}
.h3e-btn{border:1px solid var(--border-color,#555);background:var(--comfy-input-bg,#222);color:inherit;border-radius:6px;padding:3px 10px;cursor:pointer;font:inherit}
.h3e-btn:hover{border-color:#d33;color:#f88}
.h3e-toast{color:#7fd17f;font-size:11px;opacity:0;transition:opacity .2s}
.h3e-toast.h3e-show{opacity:1}
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

function viewUrl(name) {
    const slash = name.lastIndexOf("/");
    const params = new URLSearchParams({
        filename: slash >= 0 ? name.slice(slash + 1) : name,
        subfolder: slash >= 0 ? name.slice(0, slash) : "",
        type: "input",
    });
    return api.apiURL(`/view?${params}`);
}

function kindOf(file) {
    const type = file.type || "";
    const name = file.name.toLowerCase();
    if (type.startsWith("image/") || /\.(png|jpe?g|webp|bmp|gif)$/.test(name)) return "image";
    if (type.startsWith("video/") || /\.(mp4|mov|webm|mkv|avi)$/.test(name)) return "video";
    if (type.startsWith("audio/") || /\.(wav|mp3|flac|ogg|m4a|aac)$/.test(name)) return "audio";
    return "other";
}

async function upload(file) {
    const body = new FormData();
    body.append("image", file);
    const response = await api.fetchApi("/upload/image", { method: "POST", body });
    if (response.status !== 200) throw new Error(`${response.status} ${response.statusText}`);
    const data = await response.json();
    return data.subfolder ? `${data.subfolder}/${data.name}` : data.name;
}

function pickFiles(accept, multiple) {
    return new Promise((resolve) => {
        const input = el("input");
        input.type = "file";
        input.accept = accept;
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

class MediaPanel {
    constructor(node) {
        this.node = node;
        this.root = el("div", "h3e-panel");
        for (const type of ["dragenter", "dragover", "dragleave", "drop"]) {
            // keep file drops away from ComfyUI's canvas handler (which would open them as workflows)
            this.root.addEventListener(type, (e) => {
                e.preventDefault();
                e.stopPropagation();
            });
        }
    }

    async assign(slot, files) {
        const uploaded = [];
        for (const file of files) {
            try {
                uploaded.push(await upload(file));
            } catch (error) {
                console.error("[H3 Easy] upload failed", error);
                alert(`上传失败：${file.name}\n${error.message ?? error}`);
            }
        }
        if (!uploaded.length) return;
        if (slot === "refs") {
            const refs = this.refs();
            for (const name of uploaded) if (refs.length < REF_COUNT) refs.push(name);
            this.writeRefs(refs);
        } else if (slot.startsWith("ref_image_")) {
            const refs = this.refs();
            const index = Number(slot.split("_").pop()) - 1;
            refs.splice(Math.min(index, refs.length), index < refs.length ? 1 : 0, uploaded[0]);
            for (const name of uploaded.slice(1)) if (refs.length < REF_COUNT) refs.push(name);
            this.writeRefs(refs);
        } else {
            setValue(this.node, slot, uploaded[0]);
        }
        this.render();
    }

    refs() {
        return REF_SLOTS.map((name) => getValue(this.node, name)).filter(Boolean);
    }

    writeRefs(refs) {
        REF_SLOTS.forEach((name, i) => setValue(this.node, name, refs[i] || null));
    }

    removeRef(index) {
        const refs = this.refs();
        refs.splice(index, 1);
        this.writeRefs(refs);
        this.render();
    }

    dropTarget(card, accept, onFiles) {
        card.addEventListener("dragover", () => card.classList.add("h3e-over"));
        card.addEventListener("dragleave", () => card.classList.remove("h3e-over"));
        card.addEventListener("drop", (e) => {
            card.classList.remove("h3e-over");
            const files = Array.from(e.dataTransfer?.files || []).filter((f) => accept.includes(kindOf(f)));
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

    imageCard(className, label, value, onFiles, onRemove, multiple, tag) {
        const card = el("div", `h3e-card ${className}${value ? " h3e-filled" : ""}`);
        if (value) {
            const img = el("img");
            img.src = viewUrl(value);
            img.alt = label;
            card.title = `${value}\n点击替换`;
            card.append(img, this.removeButton(onRemove));
            const badge = el("span", `h3e-badge${tag ? " h3e-tag" : ""}`, tag || label);
            if (tag) {
                badge.title = "点击复制到剪贴板，粘贴进提示词";
                badge.addEventListener("click", (e) => {
                    e.stopPropagation();
                    this.copy(tag);
                });
            }
            card.append(badge);
        } else {
            const empty = el("div", "h3e-empty");
            empty.append(el("div", "h3e-plus", "+"), el("div", "", label));
            card.title = "点击选择图片，或把图片拖到这里";
            card.append(empty);
        }
        card.addEventListener("click", async () => onFiles(await pickFiles(ACCEPT.image, multiple)));
        this.dropTarget(card, ["image"], onFiles);
        return card;
    }

    mediaBlock(slot, kind, label) {
        const value = getValue(this.node, slot);
        if (!value) {
            const card = el("div", "h3e-card h3e-drop");
            const empty = el("div", "h3e-empty");
            empty.append(el("div", "h3e-plus", "+"), el("div", "", label));
            card.append(empty);
            card.addEventListener("click", async () => this.assign(slot, (await pickFiles(ACCEPT[kind])).slice(0, 1)));
            this.dropTarget(card, kind === "audio" ? ["audio", "video"] : ["video"], (files) => this.assign(slot, files.slice(0, 1)));
            return card;
        }
        const box = el("div", "h3e-media");
        box.append(el("div", "h3e-name", `${kind === "audio" ? "🎵" : "🎬"} ${value}`));
        const player = el(kind === "audio" ? "audio" : "video");
        player.controls = true;
        player.preload = "metadata";
        if (kind === "video") player.muted = true;
        player.src = viewUrl(value);
        box.append(player, this.removeButton(() => {
            setValue(this.node, slot, null);
            this.render();
        }));
        this.dropTarget(box, kind === "audio" ? ["audio", "video"] : ["video"], (files) => this.assign(slot, files.slice(0, 1)));
        return box;
    }

    section(title, hint) {
        const section = el("div", "h3e-section");
        const head = el("div", "h3e-head");
        head.append(el("span", "h3e-title", title), el("span", "h3e-hint", hint));
        section.append(head);
        return section;
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
        const root = this.root;
        root.replaceChildren();

        const frames = this.section("首帧 / 尾帧", "图文模式用；不放就是文生视频");
        const row = el("div", "h3e-row");
        for (const [slot, label] of FRAME_SLOTS) {
            row.append(this.imageCard("h3e-frame", label, getValue(this.node, slot),
                (files) => this.assign(slot, files.slice(0, 1)),
                () => { setValue(this.node, slot, null); this.render(); }, false));
        }
        frames.append(row);

        const refs = this.refs();
        const refSection = this.section(`参考图 ${refs.length}/${REF_COUNT}`, "参考模式用；提示词里写 <Picture N>");
        const grid = el("div", "h3e-grid");
        refs.forEach((value, i) => {
            grid.append(this.imageCard("h3e-ref", `参考图${i + 1}`, value,
                (files) => this.assign(`ref_image_${i + 1}`, files),
                () => this.removeRef(i), true, `<Picture ${i + 1}>`));
        });
        if (refs.length < REF_COUNT) {
            grid.append(this.imageCard("h3e-ref", "添加参考图", null, (files) => this.assign("refs", files),
                null, true));
        }
        refSection.append(grid);

        const audio = this.section("音频", "图文模式＝锁定音频（对口型，输出原声）；参考模式＝参考音频");
        audio.append(this.mediaBlock("audio_file", "audio", "点击或拖入音频（也可以是带声音的视频）"));

        const video = this.section("视频", "参考模式＝参考视频（最多读 15 秒）；图文模式＝没有单独音频时用它的音轨");
        video.append(this.mediaBlock("video_file", "video", "点击或拖入视频"));

        const foot = el("div", "h3e-foot");
        this.toastEl = el("span", "h3e-toast");
        const clear = el("button", "h3e-btn", "清空全部");
        clear.addEventListener("click", () => {
            for (const name of ALL_SLOTS) setValue(this.node, name, null);
            this.render();
        });
        foot.append(this.toastEl, clear);

        root.append(frames, refSection, audio, video, foot);
        this.fit();
    }

    fit() {
        requestAnimationFrame(() => {
            const node = this.node;
            const want = node.computeSize?.();
            if (want && node.size && node.size[1] < want[1]) node.setSize([node.size[0], want[1]]);
            node.setDirtyCanvas?.(true, true);
        });
    }

    height() {
        const refs = this.refs().length;
        const refRows = Math.ceil(Math.min(refs + 1, REF_COUNT) / 3);
        const hasAudio = !!getValue(this.node, "audio_file");
        const hasVideo = !!getValue(this.node, "video_file");
        return 30 + 150 + 30 + refRows * 128 + 30 + (hasAudio ? 82 : 58) + 30 + (hasVideo ? 220 : 58) + 40;
    }
}

app.registerExtension({
    name: "H3Easy.MediaLoader",
    nodeCreated(node) {
        if ((node.comfyClass || node.type) !== NODE || node.__h3ePanel) return;
        ensureStyle();
        for (const name of ALL_SLOTS) hideWidget(findWidget(node, name));
        const panel = new MediaPanel(node);
        node.__h3ePanel = panel;
        const widget = node.addDOMWidget("media_panel", "h3easy_media_panel", panel.root, {
            serialize: false,
            hideOnZoom: false,
            getMinHeight: () => panel.height(),
        });
        widget.serialize = false;
        const configure = node.onConfigure;
        node.onConfigure = function (...args) {
            const result = configure?.apply(this, args);
            queueMicrotask(() => panel.render());
            return result;
        };
        panel.render();
        node.setSize([Math.max(node.size?.[0] || 0, 420), node.computeSize()[1]]);
    },
});
