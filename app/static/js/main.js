// 猕猴桃订购 - 前端交互
// 说明：多地址下单的卡片增删与费用测算、面单照片上传（拍照/相册）均在
// 各模板内嵌脚本中处理；本文件保留通用交互（复制查询码 / 状态操作确认）。

// 1. 复制查询码
(function () {
  var copyBtn = document.getElementById('copy-code');
  if (!copyBtn) return;

  function done() {
    copyBtn.textContent = '已复制 ✓';
    setTimeout(function () { copyBtn.textContent = '复制查询码'; }, 2000);
  }

  function fallbackCopy(code) {
    var ta = document.createElement('textarea');
    ta.value = code;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) { /* ignore */ }
    document.body.removeChild(ta);
    done();
  }

  copyBtn.addEventListener('click', function () {
    var code = copyBtn.dataset.code || '';
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(code).then(done).catch(function () { fallbackCopy(code); });
    } else {
      fallbackCopy(code);
    }
  });
})();

// 2. 管理端状态操作二次确认（取消/退回等需要备注或确认）
(function () {
  document.querySelectorAll('form.confirm-form').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!window.confirm('确定执行该状态操作吗？')) {
        e.preventDefault();
      }
    });
  });
})();
