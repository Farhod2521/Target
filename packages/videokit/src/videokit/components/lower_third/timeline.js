const tl=gsap.timeline();
tl.fromTo('.lt',{clipPath:'inset(0 100% 0 0)'},{clipPath:'inset(0 0% 0 0)',duration:M.enter+.1,ease:M.slide},0);
pop(tl,'.mark,.solo',.25,{rotation:-20});
tl.from('.tx>*',{opacity:0,x:-40,duration:M.enter,ease:M.slide,stagger:.12},.2);
tl.to('.lt',{clipPath:'inset(0 0 0 100%)',duration:M.leave+.05,ease:M.leaveEase},P.length-M.leave-.05);
