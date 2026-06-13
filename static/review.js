(() => {
  const saveButton = document.getElementById('save-mapping');
  const downloadButton = document.getElementById('download-mapping');
  const message = document.getElementById('mapping-message');
  const saveChecksumButton = document.getElementById('save-checksum-total');
  const checksumMessage = document.getElementById('checksum-message');
  const checksumStatusLine = document.getElementById('checksum-status-line');
  const checksumStatusBadge = document.getElementById('checksum-status-badge');
  const pageCropButtons = [...document.querySelectorAll('.save-page-crop')];
  const checksumLabels = {
    user_confirmed_total_matched: '검산 일치',
    user_confirmed_total_mismatch: '검산 불일치',
    no_user_total_selected: '검산 기준 미선택',
    no_source_total: '원본 합계 없음',
    incomplete_source_scan: '합계 확인 미완료'
  };

  const collectPayload = (status) => {
    const mappingPanel = document.querySelector('.mapping-panel');
    const groups = [...document.querySelectorAll('.mapping-group')].map(group => {
      const columns = [...group.querySelectorAll('select')].map(select => ({
        column_id: select.dataset.columnId || '',
        header: select.dataset.header || '',
        suggested_field: select.dataset.suggested || '',
        selected_field: select.value
      }));
      return {
        group_id: group.dataset.groupId || '',
        columns
      };
    });
    return {
      schema_version: '1.0',
      status,
      created_at: new Date().toISOString(),
      mapping_path: mappingPanel
        ? new URL(mappingPanel.dataset.mappingPath || 'merged/mapping_suggestions.json', window.location.href).pathname
        : '',
      table_groups: groups
    };
  };

  const downloadPayload = (payload) => {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'mapping-profile.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const updateChecksumStatus = (refresh) => {
    if (!refresh || !refresh.ok || !refresh.checksum) return false;
    const status = refresh.checksum_status || refresh.checksum.status || '';
    const label = checksumLabels[status] || status || '검산 갱신';
    const text = `${label}: ${refresh.checksum.message || refresh.message || ''}`;
    if (checksumStatusLine) {
      checksumStatusLine.textContent = text;
      checksumStatusLine.dataset.checksumStatus = status;
      checksumStatusLine.classList.toggle('mapping-ok', status === 'user_confirmed_total_matched');
      checksumStatusLine.classList.toggle('merge-warning', status !== 'user_confirmed_total_matched');
    }
    if (checksumStatusBadge) checksumStatusBadge.textContent = label;
    return true;
  };

  document.querySelectorAll('.crop-control input[type="range"]').forEach(input => {
    const output = input.closest('.crop-control')?.querySelector('output');
    const update = () => {
      if (output) output.textContent = `${input.value}%`;
      const panel = input.closest('.crop-controls');
      const figure = panel?.closest('.page-image');
      const field = input.dataset.ratioField || '';
      const line = figure?.querySelector(`.crop-overlay-line[data-overlay-field="${field}"]`);
      if (line) line.style.top = `${input.value}%`;
    };
    input.addEventListener('input', update);
    update();
  });

  pageCropButtons.forEach(button => {
    button.addEventListener('click', async () => {
      const panel = button.closest('.crop-controls');
      const messageEl = panel?.querySelector('.page-crop-message');
      if (!panel) return;
      const crop = {};
      panel.querySelectorAll('input[data-ratio-field]').forEach(input => {
        crop[input.dataset.ratioField || ''] = Number(input.value) / 100;
      });
      const statePath = new URL(panel.dataset.cropStatePath || 'merged/page_crop_profile.json', window.location.href).pathname;
      const payload = {
        schema_version: '1.0',
        state_path: statePath,
        page_number: panel.dataset.pageNumber || '',
        crop
      };
      if (messageEl) messageEl.textContent = '자르기 설정을 PC에 저장하는 중입니다...';
      try {
        const response = await fetch('/api/page-crop-profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'save failed');
        if (messageEl) messageEl.textContent = '저장했습니다. --force --force-vision으로 다시 실행하면 새 청크와 AI 추출에 적용됩니다.';
      } catch (error) {
        if (messageEl) messageEl.textContent = '저장 서버가 없거나 실패했습니다. serve_review.py로 열어 주세요.';
      }
    });
  });

  if (saveButton) {
    saveButton.addEventListener('click', async () => {
      const payload = collectPayload('user_confirmed_save_request');
      if (message) message.textContent = 'PC에 매핑을 저장하는 중입니다...';
      try {
        const response = await fetch('/api/mapping-profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'save failed');
        if (message) {
          const refreshed = result.refresh?.ok;
          message.textContent = refreshed
            ? `PC profiles 폴더에 저장했고 Excel도 갱신했습니다: ${result.filename}`
            : `PC profiles 폴더에 저장했습니다: ${result.filename}`;
        }
      } catch (error) {
        if (message) message.textContent = '저장 서버가 없거나 실패했습니다. JSON 내려받기를 사용하세요.';
      }
    });
  }

  if (downloadButton) {
    downloadButton.addEventListener('click', () => {
      downloadPayload(collectPayload('user_confirmed_download'));
      if (message) message.textContent = '매핑 JSON을 내려받았습니다.';
    });
  }

  if (saveChecksumButton) {
    saveChecksumButton.addEventListener('click', async () => {
      const container = document.querySelector('.checksum-candidates');
      const selected = document.querySelector('input[name="checksum-total"]:checked');
      if (!container || !selected) {
        if (checksumMessage) checksumMessage.textContent = '먼저 원본 합계를 선택하세요.';
        return;
      }
      let candidate = {};
      try {
        candidate = JSON.parse(selected.dataset.candidate || '{}');
      } catch (error) {
        candidate = {};
      }
      const statePath = new URL(container.dataset.statePath || 'merged/review_state.json', window.location.href).pathname;
      const payload = {
        schema_version: '1.0',
        status: 'user_confirmed_review_state',
        state_path: statePath,
        checksum: {
          selected_total_id: selected.value,
          selected_total: candidate
        }
      };
      if (checksumMessage) checksumMessage.textContent = '검산 기준을 PC에 저장하는 중입니다...';
      try {
        const response = await fetch('/api/review-state', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'save failed');
        const refreshed = updateChecksumStatus(result.refresh);
        if (checksumMessage) {
          checksumMessage.textContent = refreshed
            ? '저장했고 현재 검산 요약과 Excel도 갱신했습니다.'
            : `저장했습니다. ${result.refresh?.message || '같은 명령을 다시 실행하면 검산에 반영됩니다.'}`;
        }
      } catch (error) {
        if (checksumMessage) checksumMessage.textContent = '저장 서버가 없거나 실패했습니다. serve_review.py로 열어 주세요.';
      }
    });
  }
})();
