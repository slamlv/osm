// client_multi_image_upload.js - Compatible ClearableFileInput Django
(() => {
  const MAX_WIDTH = 1200;
  const QUALITY = 0.75;
  const OUTPUT_TYPE = 'image/webp';
  const FILE_INPUT_CLASS = 'client-image';
  const FORM_CLASS = 'client-image-form';

  function getCookie(name) {
    const v = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
    return v ? v.pop() : '';
  }

  function createProgressElements(form) {
    if (form._clientProgress) return form._clientProgress;
    const container = document.createElement('div');
    container.className = 'client-upload-progress';
    container.style = 'margin-top:8px;';

    const barwrap = document.createElement('div');
    barwrap.style = 'width:100%; background:#eee; height:10px; border-radius:6px; overflow:hidden;';
    const bar = document.createElement('div');
    bar.className = 'bg-warning';
    bar.style = 'height:10px; width:0%';
    barwrap.appendChild(bar);

    const text = document.createElement('div');
    text.className = 'text-white';
    text.style = 'font-size:12px; margin-top:4px;';

    container.appendChild(barwrap);
    container.appendChild(text);
    form.appendChild(container);

    return form._clientProgress = { container, bar, text };
  }

  async function resizeAndConvert(file) {
    let imgBitmap;
    try {
      imgBitmap = window.createImageBitmap ? await createImageBitmap(file) : await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = URL.createObjectURL(file); });
    } catch {
      imgBitmap = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = URL.createObjectURL(file); });
    }

    const naturalWidth = imgBitmap.width || imgBitmap.naturalWidth;
    const naturalHeight = imgBitmap.height || imgBitmap.naturalHeight;
    let targetWidth = naturalWidth, targetHeight = naturalHeight;
    if (MAX_WIDTH && naturalWidth > MAX_WIDTH) { targetWidth = MAX_WIDTH; targetHeight = Math.round(naturalHeight * (MAX_WIDTH / naturalWidth)); }

    const canvas = document.createElement('canvas');
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext('2d');
    try { ctx.drawImage(imgBitmap, 0, 0, targetWidth, targetHeight); }
    catch {
      const tmp = URL.createObjectURL(file);
      await new Promise((res, rej) => {
        const i = new Image();
        i.onload = () => { ctx.drawImage(i, 0, 0, targetWidth, targetHeight); URL.revokeObjectURL(tmp); res(); };
        i.onerror = () => { URL.revokeObjectURL(tmp); rej(); };
        i.src = tmp;
      });
    } finally { try { if (imgBitmap && imgBitmap.close) imgBitmap.close(); } catch {} }

    return await new Promise(resolve => {
      canvas.toBlob(blob => {
        if (!blob && OUTPUT_TYPE === 'image/webp') canvas.toBlob(b2 => resolve(b2), 'image/jpeg', QUALITY);
        else resolve(blob);
      }, OUTPUT_TYPE, QUALITY);
    });
  }

  function blobToFile(blob, filename) {
    try { return new File([blob], filename, { type: blob.type }); }
    catch { blob.name = filename; return blob; }
  }

  async function navigateAndRender(url) {
    try {
      const resp = await fetch(url, { credentials: 'same-origin', method: 'GET' });
      if (!resp.ok) { window.location.assign(url); return; }
      const ct = resp.headers.get('Content-Type') || '';
      if (!ct.includes('text/html')) { window.location.assign(url); return; }
      const html = await resp.text();
      history.replaceState(null, '', url);
      document.open(); document.write(html); document.close();
    } catch { window.location.assign(url); }
  }

  function init() {
    const forms = document.querySelectorAll(`form.${FORM_CLASS}`);
    forms.forEach(f => setupForm(f));
  }

  function setupForm(form) {
    const compressedMap = new Map();
    const fileInputs = Array.from(form.querySelectorAll(`input[type=file].${FILE_INPUT_CLASS}`));

    fileInputs.forEach(input => {
      const preview = document.createElement('img');
      preview.style = 'max-width:200px; display:none; margin-top:6px; border:1px solid #ddd; padding:4px;';
      input.insertAdjacentElement('afterend', preview);
      let info = null;

      input.addEventListener('change', async e => {
        const f = e.target.files && e.target.files[0];
        if (preview._url) try { URL.revokeObjectURL(preview._url); } catch {}
        if (!f) { compressedMap.delete(input); preview.style.display='none'; if (info) info.textContent=''; return; }

        preview._url = URL.createObjectURL(f); preview.src = preview._url; preview.style.display='';

        try {
          const blob = await resizeAndConvert(f);
          const base = f.name.includes('.') ? f.name.substring(0, f.name.lastIndexOf('.')) : f.name;
          const ext = blob.type === 'image/webp' ? 'webp' : (blob.type === 'image/jpeg' ? 'jpg' : 'img');
          const filename = base + '.' + ext;
          compressedMap.set(input, [{ blob, filename }]);

          if (!info) { info = document.createElement('div'); info.className='text-white'; info.style='font-size:12px;margin-top:4px;color:inherit'; input.insertAdjacentElement('afterend', info); }
          info.textContent = `Prêt : ${(f.size/1024).toFixed(1)}KB → ${(blob.size/1024).toFixed(1)}KB`;
          if (preview._url) try { URL.revokeObjectURL(preview._url); } catch {}
          preview._url = URL.createObjectURL(blob); preview.src = preview._url;
        } catch {
          compressedMap.delete(input); preview.style.display='none';
          if (!info) { info = document.createElement('div'); info.className='text-white'; info.style='font-size:12px;margin-top:4px;color:inherit'; input.insertAdjacentElement('afterend', info); }
          info.textContent = 'Erreur traitement image côté client';
        }
      });
    });

    form.addEventListener('submit', async ev => {
      ev.preventDefault();
      const fd = new FormData(form);

      fileInputs.forEach(input => {
        const clearCheckbox = form.querySelector(`input[name="${input.name}-clear"]`);
        const isClearChecked = clearCheckbox?.checked;

        if (isClearChecked) {
          // Si clear est coché, on vide le champ file pour que Django supprime l'image
          input.value = '';
          compressedMap.delete(input);
        } else {
          const arr = compressedMap.get(input);
          if (arr && arr.length) {
            fd.delete(input.name);
            arr.forEach(info => fd.append(input.name, info.blob, info.filename));
          }
        }
      });

      const prog = createProgressElements(form);
      prog.bar.style.width='0%'; prog.text.textContent=''; prog.container.style.display='';

      const xhr = new XMLHttpRequest();
      const action = form.getAttribute('action') || window.location.href;
      const method = (form.getAttribute('method') || 'POST').toUpperCase();
      xhr.open(method, action, true);
      const csrftoken = getCookie('csrftoken') || form.querySelector('[name=csrfmiddlewaretoken]')?.value;
      if (csrftoken) xhr.setRequestHeader('X-CSRFToken', csrftoken);

      const controls = Array.from(form.querySelectorAll('input,button,textarea,select'));
      controls.forEach(c => c.disabled = true);

      xhr.upload.onprogress = ev => {
        if (ev.lengthComputable) {
          const pct = Math.round(ev.loaded / ev.total * 100);
          prog.bar.style.width = pct + '%';
          prog.text.textContent = `${pct}%`;
        } else prog.text.textContent = 'Envoi...';
      };

      xhr.onload = async () => {
        controls.forEach(c => c.disabled = false);
        if (xhr.responseURL) { await navigateAndRender(xhr.responseURL); return; }
        if (xhr.status >= 200 && xhr.status < 300) { prog.bar.style.width='100%'; prog.text.textContent='Téléversement terminé'; }
        else { prog.textContent = `Erreur upload (${xhr.status})`; alert(`Erreur upload (${xhr.status})`); }
      };

      xhr.onerror = () => { controls.forEach(c => c.disabled = false); prog.textContent='Erreur réseau'; alert('Erreur réseau'); };

      xhr.send(fd);
    });
  }

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
