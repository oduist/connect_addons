/** @odoo-module **/

export function setFocus(el) {
    // The softphone only mounts its dial input on the screens that use it,
    // so callers cannot promise the element is there.
    if (!el) return
    setTimeout(() => {
        if (el.isConnected) el.focus()
    }, 100)
}

export function getNotifyMessage(isPartner, contact) {
    const partnerAvatar = isPartner ? `
            <div>
                <img alt="Avatar" style="max-height: 100px; max-width: 100px;" class="rounded-circle" src="${contact.partnerIconUrl}"/>
            </div>` : ''
    const partnerRef = isPartner ? `
            <p class="text-center"><strong>Partner:</strong>
                <a href='/web#id=${contact.partnerId}&model=res.partner&view_type=form'>
                    ${contact.partnerName}
                </a>
            </p>` : ''
    return `
            <div class="d-flex align-items-center justify-content-center">
                ${partnerAvatar}
                <div>
                    <p class="text-center">Incoming call at ${contact.phone_number}</p>
                </div>
                ${partnerRef}
            </div>
        `
}

export function cleanNumber(number) {
    return number ? number.replace(/[^0-9+]/g, '') : ''
}

export function dialTone(key) {
    const keyFrequency = {
        1: [697.0, 1209.0],
        2: [697.0, 1336.0],
        3: [697.0, 1477.0],
        4: [770.0, 1209.0],
        5: [770.0, 1336.0],
        6: [770.0, 1477.0],
        7: [852.0, 1209.0],
        8: [852.0, 1336.0],
        9: [852.0, 1477.0],
        0: [941.0, 1336.0],
        "*": [941.0, 1209.0],
        "#": [941.0, 1477.0],
    }

    const [freq1, freq2] = keyFrequency[key]

    let contextClass = (window.AudioContext ||
        window.webkitAudioContext ||
        window.mozAudioContext ||
        window.oAudioContext ||
        window.msAudioContext)

    if (contextClass) {
        let context = new contextClass()

        let oscillator1 = context.createOscillator()
        oscillator1.frequency.value = freq1
        let gainNode = context.createGain ? context.createGain() : context.createGainNode();
        oscillator1.connect(gainNode, 0, 0)
        gainNode.connect(context.destination)
        gainNode.gain.value = .1
        oscillator1.start ? oscillator1.start(0) : oscillator1.noteOn(0)

        let oscillator2 = context.createOscillator()
        oscillator2.frequency.value = freq2
        gainNode = context.createGain ? context.createGain() : context.createGainNode()
        oscillator2.connect(gainNode)
        gainNode.connect(context.destination)

        gainNode.gain.value = .1
        oscillator2.start ? oscillator2.start(0) : oscillator2.noteOn(0)
        setTimeout(() => {
            oscillator1.disconnect()
            oscillator2.disconnect()
        }, 100)
    }
}

export const browser = {chrome: 'chrome', safari: 'safari', firefox: 'firefox'}

// Avatar placeholders.
//
// There is no default contact image to fall back on: the path every module
// points at, /connect/static/src/images/default_contact.jpg, does not exist
// (core ships no static/src/images at all), so it renders as a broken image.
// A coloured initial is what the design calls for anyway, and it cannot 404.

const AVATAR_TONES = [
    '#3E7F5C', '#8B5AA8', '#C0603C', '#3E6EA8', '#4E4A8C', '#6C4C84', '#2F7D74',
]

/** First letter of a name, or of a number, for a placeholder tile. */
export function contactInitial(text) {
    const trimmed = (text || '').trim()
    if (!trimmed) return ''
    const letter = trimmed.replace(/[^\p{L}\p{N}]/gu, '').charAt(0)
    return letter ? letter.toUpperCase() : ''
}

/** A stable tile colour for `text`, so the same peer is always the same hue. */
export function contactTone(text) {
    const trimmed = (text || '').trim()
    if (!trimmed) return AVATAR_TONES[0]
    let hash = 0
    for (let i = 0; i < trimmed.length; i++) {
        hash = (hash * 31 + trimmed.charCodeAt(i)) >>> 0
    }
    return AVATAR_TONES[hash % AVATAR_TONES.length]
}
