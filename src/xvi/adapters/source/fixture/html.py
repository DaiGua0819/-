# ruff: noqa: E501

FIXTURE_HTML = """
<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>XVI Fixture</title></head>
<body>
  <main data-xvi-authenticated="true">
    <input data-xvi="search-input" aria-label="搜索" />
    <a data-xvi="result-card" data-xvi-note-url="fixture-note-1" href="fixture-note-1">门店陈列示例</a>
    <section id="note" data-xvi="note-container" hidden>
      <button data-xvi="note-close" aria-label="关闭">关闭</button>
      <div data-xvi="carousel-viewport">
        <canvas id="frame" width="640" height="480"></canvas>
      </div>
      <button data-xvi="carousel-download" aria-label="下载">下载</button>
      <button data-xvi="carousel-next" aria-label="下一张">下一张</button>
    </section>
  </main>
<script>
  const frames = ["steelblue", "seagreen", "darkorange"];
  let index = 0;
  const note = document.querySelector('#note');
  const frame = document.querySelector('#frame');
  const context = frame.getContext('2d');
  const next = document.querySelector('[data-xvi="carousel-next"]');

  function drawFrame() {
    context.fillStyle = frames[index];
    context.fillRect(0, 0, frame.width, frame.height);
    context.fillStyle = 'white';
    context.fillRect(40 + index * 120, 70, 180, 120);
    context.fillStyle = 'black';
    context.font = '48px sans-serif';
    context.fillText(`frame-${index + 1}`, 50, 280);
  }

  document.querySelector('[data-xvi="result-card"]').addEventListener('click', (event) => {
    event.preventDefault();
    note.hidden = false;
    drawFrame();
  });
  document.querySelector('[data-xvi="note-close"]').addEventListener('click', () => note.hidden = true);
  next.addEventListener('click', () => {
    index = (index + 1) % frames.length;
    drawFrame();
  });
  document.querySelector('[data-xvi="carousel-download"]').addEventListener('click', () => {
    frame.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `fixture-${index + 1}.png`;
      link.click();
      URL.revokeObjectURL(url);
    }, 'image/png');
  });
</script>
</body>
</html>
"""
