// 视频语音替换工具 - 前端交互逻辑
let currentTaskId = null;

const uploadBtn = document.getElementById("uploadBtn");
const videoInput = document.getElementById("videoInput");
const uploadError = document.getElementById("uploadError");

const step2 = document.getElementById("step2");
const step3 = document.getElementById("step3");
const scriptText = document.getElementById("scriptText");
const downloadScriptBtn = document.getElementById("downloadScriptBtn");

const scriptFileInput = document.getElementById("scriptFileInput");
const applyBtn = document.getElementById("applyBtn");
const applyStatus = document.getElementById("applyStatus");
const applyError = document.getElementById("applyError");
const downloadLink = document.getElementById("downloadLink");

uploadBtn.addEventListener("click", async () => {
  uploadError.textContent = "";
  const file = videoInput.files[0];
  if (!file) {
    uploadError.textContent = "请先选择一个视频文件";
    return;
  }

  uploadBtn.disabled = true;
  uploadBtn.textContent = "处理中，请稍候...";

  const formData = new FormData();
  formData.append("video", file);

  try {
    const resp = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.error || "上传失败");
    }

    currentTaskId = data.task_id;
    scriptText.value = data.script;
    step2.classList.remove("hidden");
    step3.classList.remove("hidden");
  } catch (err) {
    uploadError.textContent = "错误：" + err.message;
  } finally {
    uploadBtn.disabled = false;
    uploadBtn.textContent = "上传并识别";
  }
});

downloadScriptBtn.addEventListener("click", () => {
  if (!currentTaskId) return;
  window.location.href = `/api/script/${currentTaskId}`;
});

scriptFileInput.addEventListener("change", async () => {
  const file = scriptFileInput.files[0];
  if (!file) return;
  const text = await file.text();
  scriptText.value = text;
});

applyBtn.addEventListener("click", async () => {
  applyError.textContent = "";
  applyStatus.textContent = "";
  downloadLink.classList.add("hidden");

  if (!currentTaskId) {
    applyError.textContent = "请先完成第一步上传视频";
    return;
  }

  const content = scriptText.value;
  if (!content.trim()) {
    applyError.textContent = "台词内容不能为空";
    return;
  }

  applyBtn.disabled = true;
  applyStatus.textContent = "正在合成语音并生成视频，这个过程可能需要几分钟，请耐心等待...";

  const blob = new Blob([content], { type: "text/plain" });
  const formData = new FormData();
  formData.append("script", blob, "script.txt");

  try {
    const resp = await fetch(`/api/apply/${currentTaskId}`, { method: "POST", body: formData });
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.error || "处理失败");
    }

    applyStatus.textContent = "处理完成！";
    downloadLink.href = data.download_url;
    downloadLink.classList.remove("hidden");
  } catch (err) {
    applyError.textContent = "错误：" + err.message;
    applyStatus.textContent = "";
  } finally {
    applyBtn.disabled = false;
  }
});
