const b=P.beats;
const tl=gsap.timeline();
if(document.querySelector('.l')){enter(tl,'.l',0,{y:-50});}
const hit=b.slam!==undefined?b.slam:.45;
slam(tl,'.pw',hit,'.w');
if(document.querySelector('.ic')){tl.to('.ic',{scale:1.25,duration:.25,yoyo:true,repeat:5,ease:'sine.inOut',transformOrigin:'50% 50%'},hit+.3);}
twinkle(tl,'.s',hit+.25);
leave(tl,['.w','.s']);
