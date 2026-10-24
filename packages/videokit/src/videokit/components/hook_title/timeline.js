const t=document.querySelector('.t');
t.innerHTML=t.textContent.split(' ').map(w=>'<span class="m"><span class="w"></span></span>').join(' ');
t.querySelectorAll('.w').forEach((el,i)=>{el.textContent=P.text.split(' ')[i];});
const tl=gsap.timeline();
tl.from('.w',{yPercent:110,duration:.2,ease:'back.out(1.6)',stagger:.015},0);
tl.from('.bar',{scaleX:0,transformOrigin:'0 50%',duration:.3,ease:'power3.out'},.1);
leave(tl,'.box',{y:-40});
if(P.scrim){tl.to('.scrim',{opacity:0,duration:M.leave},P.length-M.leave);}
