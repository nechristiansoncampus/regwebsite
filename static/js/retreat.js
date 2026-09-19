// Scroll progress bar + subtle scroll-reactive motion on the reel card
const scroller = document.getElementById('scroller');
const progress = document.querySelector('.progress');

function onScroll(){
  const max = scroller.scrollHeight - scroller.clientHeight;
  const y = scroller.scrollTop;
  const p = max > 0 ? y / max : 0;

  if (progress) {
    progress.style.transform = `scaleX(${p})`;
  }
}

scroller.addEventListener('scroll', onScroll, { passive: true });
onScroll();

// Reveal-on-scroll
const revealEls = document.querySelectorAll('.reveal');
const revealObserver = new IntersectionObserver((entries) => {
  for(const entry of entries){
    if(entry.isIntersecting) entry.target.classList.add('in');
  }
}, { root: scroller, threshold: 0.12 });

revealEls.forEach(element => revealObserver.observe(element));

document.addEventListener('DOMContentLoaded', () => {
  function initSoundToggle(videoId, toggleId) {
    const video = document.getElementById(videoId);
    const toggle = document.getElementById(toggleId);

    if (!video || !toggle) {
      console.warn('Sound toggle init missing:', { videoId, toggleId });
      return;
    }

    function setSoundUI(isOn){
      toggle.setAttribute('aria-pressed', String(isOn));
      toggle.setAttribute('aria-label', isOn ? 'Turn sound off' : 'Turn sound on');
    }

    video.muted = true;
    video.setAttribute('muted', '');
    setSoundUI(false);

    toggle.addEventListener('click', async (event) => {
      event.preventDefault();
      event.stopPropagation();

      try {
        const turningOn = video.muted;

        if (turningOn) {
          video.muted = false;
          video.removeAttribute('muted');
          video.volume = 1;
          await video.play();
          setSoundUI(true);
        } else {
          video.muted = true;
          video.setAttribute('muted', '');
          setSoundUI(false);
        }
      } catch (error) {
        video.muted = true;
        video.setAttribute('muted', '');
        setSoundUI(false);
        console.warn('Sound toggle blocked:', error);
      }
    });
  }

  initSoundToggle('heroVideo', 'soundToggle');
  initSoundToggle('reel2', 'soundToggle2');
});

(() => {
  const registerButton = document.getElementById('floatingRegister');
  const sections = ['top', 'details', 'schedule', 'register']
    .map(id => document.getElementById(id));

  if(!registerButton || !scroller || sections.some(section => !section)) return;

  const state = {
    top: false,
    details: false,
    schedule: false,
    register: false
  };

  const update = () => {
    const show = (state.details || state.schedule) && !(state.top || state.register);
    registerButton.classList.toggle('isOn', show);
  };

  const sectionObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      state[entry.target.id] = entry.isIntersecting;
    });
    update();
  }, {
    root: scroller,
    threshold: 0.45
  });

  sections.forEach(element => sectionObserver.observe(element));
  update();
})();
