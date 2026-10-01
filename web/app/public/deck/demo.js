// Chapter buttons seek the demo video (external file: the site CSP blocks inline scripts).
const v=document.getElementById("v");
document.querySelectorAll(".chap button").forEach(b=>b.addEventListener("click",()=>{v.currentTime=+b.dataset.t;v.play().catch(()=>{});v.scrollIntoView({behavior:"smooth",block:"center"});}));
