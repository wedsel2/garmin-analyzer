// Shows the distance and the target time of an event only for a sport that has
// them. Without this script they stay in view and the server leaves them out.
document.addEventListener("DOMContentLoaded", () => {
  const sport = document.getElementById("sport");
  const fields = document.querySelector("[data-for-sports]");
  if (!sport || !fields) return;
  const sports = fields.dataset.forSports.split(",");
  const show = () => {
    fields.hidden = !sports.includes(sport.value);
  };
  sport.addEventListener("change", show);
  show();
});
