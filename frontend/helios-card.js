//Client for /helios-card.
//
//Two jobs: apply the same language switcher / data-i18n machinery
//the upload page uses, and fetch the rendered Helios README from
//the server-side `/api/helios-readme` endpoint. The README HTML is
//trusted (it comes from our own repo, rendered server-side) so we
//inject it via innerHTML directly.

import {
    SUPPORTED_LANGS,
    LANG_FLAGS,
    LANG_LABELS,
    TRANSLATIONS,
    applyTranslations,
    detectInitialLang,
    persistLang,
} from '/static/i18n.js';

let activeLang = detectInitialLang();
applyTranslations(activeLang);

const langSwitcher = document.getElementById('lang-switcher');
if (langSwitcher)
{
    SUPPORTED_LANGS.forEach((lang) =>
    {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'lang-flag';
        btn.dataset.lang = lang;
        btn.title = LANG_LABELS[lang];
        btn.setAttribute('aria-label', LANG_LABELS[lang]);
        btn.textContent = LANG_FLAGS[lang];
        if (lang === activeLang) btn.classList.add('active');
        btn.addEventListener('click', () => switchLang(lang));
        langSwitcher.appendChild(btn);
    });
}

function switchLang(lang)
{
    if (!SUPPORTED_LANGS.includes(lang)) return;
    activeLang = lang;
    persistLang(lang);
    applyTranslations(lang);
    document.querySelectorAll('.lang-flag').forEach((btn) =>
    {
        btn.classList.toggle('active', btn.dataset.lang === lang);
    });
    //Re-emit the release-tag append on the meta line; the i18n
    //pass above overwrote it with the bare translated source-note.
    appendReleaseTagToMeta();
}

const meta = document.getElementById('readme-meta');
const content = document.getElementById('readme-content');
let lastRelease = null;   // { tag, url } once fetched

function appendReleaseTagToMeta()
{
    if (!meta || !lastRelease) return;
    const link = document.createElement('a');
    link.href = lastRelease.url;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = lastRelease.tag;
    meta.appendChild(document.createTextNode(' '));
    meta.appendChild(link);
}

async function loadReadme()
{
    try
    {
        const resp = await fetch('/api/helios-readme', { headers: { 'Accept': 'application/json' } });
        const data = await resp.json();
        if (!resp.ok || !data.html)
        {
            showError(data.release_url);
            return;
        }
        content.innerHTML = data.html;
        lastRelease = { tag: data.release_tag, url: data.release_url };
        appendReleaseTagToMeta();
        rewriteRelativeImageUrls();
    }
    catch (err)
    {
        showError('https://github.com/ReikanYsora/Helios');
    }
}

function showError(repoUrl)
{
    const errorMsg = TRANSLATIONS[activeLang]?.heliosCardError
        || 'Could not load the Helios README right now. Try again in a minute, or visit the repository directly:';
    content.innerHTML = '';
    const p = document.createElement('p');
    p.className = 'readme-error';
    p.textContent = errorMsg + ' ';
    const a = document.createElement('a');
    a.href = repoUrl;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = repoUrl;
    p.appendChild(a);
    content.appendChild(p);
}

//The README references images with absolute raw.githubusercontent
//URLs already so most things just work, but markdown renders
//relative paths verbatim. Walk the injected content and rewrite
//anything that still looks like a repo-relative href.
function rewriteRelativeImageUrls()
{
    const base = 'https://raw.githubusercontent.com/ReikanYsora/Helios/main/';
    content.querySelectorAll('img[src]').forEach((img) =>
    {
        const src = img.getAttribute('src');
        if (src && !/^https?:\/\//i.test(src) && !src.startsWith('//'))
        {
            img.src = base + src.replace(/^\.?\/+/, '');
        }
    });
    content.querySelectorAll('a[href]').forEach((a) =>
    {
        const href = a.getAttribute('href');
        if (href && !/^https?:\/\//i.test(href) && !href.startsWith('#') && !href.startsWith('/') && !href.startsWith('mailto:'))
        {
            a.href = base + href.replace(/^\.?\/+/, '');
            a.target = '_blank';
            a.rel = 'noopener';
        }
    });
}

loadReadme();
