// Copies the text of the field a button names in data-copy. Without this script
// the button stays hidden and the text can be selected or saved as a file.
document.addEventListener("DOMContentLoaded", () => {
  for (const button of document.querySelectorAll("[data-copy]")) {
    const field = document.getElementById(button.dataset.copy);
    const copied = document.querySelector("[data-copied]");
    if (!field) continue;
    button.hidden = false;
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(field.value);
      } catch {
        // A browser that keeps the clipboard to itself: select it for the user to copy.
        field.focus();
        field.select();
        return;
      }
      if (copied) copied.hidden = false;
    });
  }
});
