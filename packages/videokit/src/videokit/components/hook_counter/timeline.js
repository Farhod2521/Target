const v=document.querySelector('.v');
const b=P.beats;
const tl=gsap.timeline();
const land=b.land!==undefined?b.land:Math.min(1.4,P.length*.4);
tl.from('.n',{scale:.6,opacity:0,duration:.3,ease:'back.out(2)'},0);
const m=P.value.match(/^(\D*)(\d[\d ]*)(.*)$/);
if(m&&!/[.,]\d/.test(m[3])){
  const goal=parseInt(m[2].replace(/ /g,''),10);
  const grouped=/ /.test(m[2]);
  const show=x=>{const s=String(Math.round(x));v.textContent=m[1]+(grouped?s.replace(/\B(?=(\d{3})+(?!\d))/g,' '):s)+m[3];};
  if(goal>0){const o={v:0};show(0);
    tl.to(o,{v:goal,duration:Math.max(.3,land-.05),ease:'power2.in',onUpdate:()=>show(o.v)},.05);
    tl.set(v,{textContent:P.value},land);}
}
tl.fromTo('.n',{scale:1},{scale:1.12,duration:.12,yoyo:true,repeat:1,ease:'power2.out'},land);
twinkle(tl,'.s',land);
const hit=b.slam!==undefined?b.slam:land+.5;
if(document.querySelector('.pw')){slam(tl,'.pw',hit,'.w');}
const rise=b.rise!==undefined?b.rise:hit+.6;
if(document.querySelector('.cw')){enter(tl,'.cw',rise,{y:60,ease:M.pop});}
leave(tl,['.w','.s']);
