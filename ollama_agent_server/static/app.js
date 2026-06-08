const $ = (id) => document.getElementById(id);
let pollTimer = null;
let renderedSteps = 0;

function headers() {
  const apiKey = $('apiKey').value.trim();
  return {
    'Content-Type': 'application/json',
    ...(apiKey ? {'X-API-Key': apiKey} : {}),
  };
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, (ch) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[ch]));
}

function setStatus(status) {
  $('jobStatus').textContent = status;
  $('jobStatus').className = `pill ${status}`;
}

function addMessage(role, html) {
  const article = document.createElement('article');
  article.className = `message ${role}`;
  article.innerHTML = `<div class="avatar">${role === 'user' ? 'YOU' : 'AI'}</div><div class="bubble">${html}</div>`;
  $('transcript').appendChild(article);
  $('transcript').scrollTop = $('transcript').scrollHeight;
  return article.querySelector('.bubble');
}

function renderStep(step) {
  const action = step.action;
  if (action.type === 'final') {
    addMessage('assistant', `<strong>최종 답변</strong><p>${escapeHtml(action.answer).replace(/\n/g, '<br>')}</p>`);
    return;
  }
  const result = step.result || {};
  const ok = result.exit_code === 0 && !result.timed_out;
  const stdout = result.stdout ? `<div class="step"><div class="step-header"><span>stdout</span></div><pre class="code stdout">${escapeHtml(result.stdout)}</pre></div>` : '';
  const stderr = result.stderr ? `<div class="step"><div class="step-header"><span>stderr</span></div><pre class="code stderr">${escapeHtml(result.stderr)}</pre></div>` : '';
  addMessage('assistant', `
    <strong>Step ${step.index}: ${escapeHtml(action.thought)}</strong>
    <div class="step">
      <div class="step-header"><span>command</span><span>${ok ? 'exit 0' : `exit ${result.exit_code ?? 'timeout'}`}</span></div>
      <pre class="code">${escapeHtml(action.command)}</pre>
    </div>
    ${stdout}${stderr}
  `);
}

async function refreshHost() {
  try {
    const health = await fetch('/health').then((r) => r.json());
    $('health').textContent = pretty(health);
    if (!$('model').value) $('model').placeholder = health.default_model;
  } catch (error) {
    $('health').textContent = String(error);
  }
  try {
    const models = await fetch('/v1/models', {headers: headers()}).then((r) => r.json());
    $('models').textContent = pretty(models.models?.map((m) => m.name) ?? models);
  } catch (error) {
    $('models').textContent = `모델 조회 실패: ${error}`;
  }
}

async function pollJob(jobId) {
  const job = await fetch(`/v1/jobs/${jobId}`, {headers: headers()}).then(async (r) => {
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  });
  setStatus(job.status);
  $('jobId').textContent = `job: ${job.job_id}`;
  for (const step of job.steps.slice(renderedSteps)) renderStep(step);
  renderedSteps = job.steps.length;
  if (job.status === 'succeeded' || job.status === 'failed') {
    clearInterval(pollTimer);
    pollTimer = null;
    $('send').disabled = false;
    if (job.status === 'failed') addMessage('assistant', `<strong>오류</strong><p>${escapeHtml(job.error || 'unknown error')}</p>`);
  }
}

$('refresh').addEventListener('click', refreshHost);
$('promptForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  clearInterval(pollTimer);
  renderedSteps = 0;
  setStatus('queued');
  $('send').disabled = true;
  const payload = {
    prompt: $('prompt').value,
    model: $('model').value.trim() || null,
    workspace: $('workspace').value.trim() || null,
    max_steps: Number($('maxSteps').value || 12),
    temperature: Number($('temperature').value || 0.2),
  };
  addMessage('user', `<strong>요청</strong><p>${escapeHtml(payload.prompt).replace(/\n/g, '<br>')}</p>`);
  try {
    const started = await fetch('/v1/jobs', {method: 'POST', headers: headers(), body: JSON.stringify(payload)}).then(async (r) => {
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    });
    $('jobId').textContent = `job: ${started.job_id}`;
    await pollJob(started.job_id);
    pollTimer = setInterval(() => pollJob(started.job_id).catch((error) => {
      clearInterval(pollTimer);
      $('send').disabled = false;
      setStatus('failed');
      addMessage('assistant', `<strong>폴링 오류</strong><p>${escapeHtml(error)}</p>`);
    }), 1500);
  } catch (error) {
    $('send').disabled = false;
    setStatus('failed');
    addMessage('assistant', `<strong>시작 실패</strong><p>${escapeHtml(error)}</p>`);
  }
});

refreshHost();
