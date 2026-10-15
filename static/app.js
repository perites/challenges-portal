(() => {
  const toastBox = document.getElementById("toasts");

  function showToast(el) {
    const hide = () => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 300);
    };
    requestAnimationFrame(() => el.classList.add("show"));
    setTimeout(hide, 4000);
    el.addEventListener("click", hide);
  }

  window.toast = (message, kind = "ok") => {
    const el = document.createElement("div");
    el.className = `toast toast-${kind}`;
    el.textContent = message;
    toastBox.appendChild(el);
    showToast(el);
  };

  // flashed messages rendered by the server
  toastBox.querySelectorAll(".toast").forEach(showToast);

  async function toggleStar(form) {
    const button = form.querySelector("button");
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch" },
      });
      const data = await response.json();
      if (!response.ok) {
        toast(data.error, "error");
        return;
      }
      button.classList.toggle("on", data.starred);
      button.setAttribute("aria-pressed", data.starred);
      button.querySelector(".count").textContent = data.count;
      toast(data.starred ? "starred" : "unstarred");
    } catch {
      toast("something went wrong, try again", "error");
    }
  }

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form.matches(".star-form")) {
      event.preventDefault();
      toggleStar(form);
    } else if (form.dataset.confirm && !confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });

  document.querySelectorAll("[data-fullscreen]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById(button.dataset.fullscreen).requestFullscreen();
    });
  });
})();
