(function () {
  const SVG = "http://www.w3.org/2000/svg";

  /** 决策点图标：方框表示由人批复，批复后框内打勾；线条取当前文字颜色，随节点状态变色。 */
  function decisionIcon(checked) {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("class", "decision-icon");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const paths = ["M4.5 2h7A2.5 2.5 0 0 1 14 4.5v7a2.5 2.5 0 0 1-2.5 2.5h-7A2.5 2.5 0 0 1 2 11.5v-7A2.5 2.5 0 0 1 4.5 2Z"];
    if (checked) paths.push("M5.1 8.2 7.1 10.2 10.9 6.1");
    paths.forEach((d) => {
      const path = document.createElementNS(SVG, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    });
    return svg;
  }

  const trashSvg = '<svg class="run-delete-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M6.1 1.8h3.8l.35 1.15H13.2v1.25H2.8V2.95h2.95L6.1 1.8zM4.15 5.2h7.7l-.62 8.15c-.04.45-.42.8-.87.8H5.64c-.45 0-.83-.35-.87-.8L4.15 5.2zM6.55 6.7v5.15h1.2V6.7H6.55zm2.7 0v5.15h1.2V6.7H9.25z"/></svg>';

  window.geniIcons = { decisionIcon, trashSvg };
})();
