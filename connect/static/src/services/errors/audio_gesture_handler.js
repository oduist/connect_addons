/** @odoo-module **/

import {registry} from "@web/core/registry"

/**
 * Safari refuses audio output selection until the page has a user gesture.
 *
 * `HTMLAudioElement.setSinkId()` is gated behind a user gesture in Safari, and
 * the Twilio Voice SDK calls it from inside its own sound playback
 * (`Sound.play()` -> `AudioPlayer.setSinkId`) without handing the promise back
 * to us. There is nothing to catch: the rejection escapes to `window`, and the
 * web client raises a full error dialog over a failure that is both expected
 * and harmless -- the browser simply keeps using the default output device,
 * and playback works normally once the user has clicked anything.
 *
 * This has to be an `error_handlers` entry rather than an `unhandledrejection`
 * listener in the phone component: the web client installs its own listener at
 * startup, long before the component mounts, so a listener added later runs
 * second and cannot stop the dialog. The registry is the supported seam --
 * returning true breaks the handler loop, and `sequence` below 100 puts this
 * ahead of `defaultHandler`, which is what opens the dialog.
 *
 * Matched narrowly on purpose. A denied microphone is also a
 * `NotAllowedError`, and that one must keep surfacing: it is the difference
 * between "the ringtone came out of the wrong speaker" and "nobody can hear
 * you".
 */
function isAudioGestureError(error) {
    if (!error || error.name !== "NotAllowedError") {
        return false
    }
    return /user gesture|setSinkId/i.test(String(error.message || ""))
}

export function connectAudioGestureHandler(env, error, originalError) {
    // The service unwraps `cause` chains into originalError, but an
    // unhandled rejection can also arrive with the reason still on `cause`.
    if (!isAudioGestureError(originalError) && !isAudioGestureError(error && error.cause)) {
        return false
    }
    console.warn(
        "[Connect Phone] The browser refused to choose an audio output device "
        + "before the page had been interacted with (Safari requires a user "
        + "gesture). The default output device is used instead, and sounds play "
        + "normally once the phone has been clicked.",
        originalError || error,
    )
    if (error && error.event) {
        error.event.preventDefault()
    }
    return true
}

registry
    .category("error_handlers")
    .add("connectAudioGestureHandler", connectAudioGestureHandler, {sequence: 95})
