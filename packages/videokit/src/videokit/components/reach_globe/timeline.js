const b=P.beats;
const tl=gsap.timeline();
tl.fromTo('.pn',{clipPath:'inset(0 0 100% 0)'},{clipPath:'inset(0 0 0% 0)',duration:.35,ease:M.slide},0);
typeIn(tl,document.querySelector('.tt'),.1,.35);
const lands=b.lands!==undefined?b.lands:.9;
pop(tl,'.pw',lands);
tl.fromTo('.gb',{scale:.4,opacity:0,rotation:-20},{scale:1,opacity:1,rotation:0,duration:.6,ease:'back.out(1.6)',transformOrigin:'50% 50%'},.15);
const mer=[...document.querySelectorAll('.mer ellipse')];
const turn={p:0};
const spin=()=>mer.forEach((e,i)=>e.setAttribute('rx',Math.abs(Math.cos(((i/5+turn.p*.6)%1)*Math.PI))*100));
spin();
tl.to(turn,{p:1,duration:P.length,ease:'none',onUpdate:spin},0);
tl.fromTo('.orb',{strokeDashoffset:0},{strokeDashoffset:-160,duration:P.length,ease:'none'},0);
const spots=[[22,-28],[-60,-38],[-34,30],[64,22],[-6,62],[70,-50]];
const tags=[...document.querySelectorAll('.tag')];
const said=b.places||[];
const pins=document.querySelector('.pins'),arcs=document.querySelector('.arcs');
const home=document.querySelector('.hm').textContent.trim();
const make=(n,a)=>{const e=document.createElementNS(document.querySelector('.gb').namespaceURI,n);for(const k in a)e.setAttribute(k,a[k]);return e;};
const count=Math.max(tags.length,5);
let at=lands+.15;
spots.slice(0,count+1).forEach((p,i)=>{
  const g=make('g',{transform:'translate('+p[0]+','+p[1]+')'});
  g.appendChild(make('circle',{r:i?7:13,class:i?'':'home'}));
  if(!i&&home){const t=make('text',{y:5,class:'hl'});t.textContent=home;g.appendChild(t);}
  pins.appendChild(g);
  if(!i){tl.fromTo(g,{scale:0},{scale:1,duration:.3,ease:'back.out(3)',svgOrigin:p[0]+' '+p[1]},.5);return;}
  at=Math.max(said[i-1]!==undefined?said[i-1]:lands+.15+i*.16,at+.1);
  const mx=(spots[0][0]+p[0])/2,my=(spots[0][1]+p[1])/2-40;
  const path=make('path',{d:'M'+spots[0][0]+' '+spots[0][1]+' Q'+mx+' '+my+' '+p[0]+' '+p[1]});
  arcs.appendChild(path);
  tl.to(path,{strokeDashoffset:0,duration:.35,ease:'power2.out'},at-.2);
  tl.fromTo(g,{scale:0},{scale:1,duration:.3,ease:'back.out(3)',svgOrigin:p[0]+' '+p[1]},at);
  if(tags[i-1]){pop(tl,tags[i-1],at,{transformOrigin:'0% 50%'});}
});
tl.to('.pn',{clipPath:'inset(0 0 100% 0)',duration:M.leave,ease:M.leaveEase},P.length-M.leave);
