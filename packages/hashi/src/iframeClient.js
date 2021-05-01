import Mediator from './mediator';
import LocalStorage from './localStorage';
import SessionStorage from './sessionStorage';
import Cookie from './cookie';
import SCORM from './SCORM';
import Kolibri from './kolibri';
import patchIndexedDB from './patchIndexedDB';
import { events, nameSpace } from './hashiBase';

/*
 * This class is initialized inside the context of a sandboxed iframe.
 * It provides shims for various APIs that would otherwise be blocked
 * inside a sandboxed iframe context, and communicates persistent data
 * via window.postMessage, to allow for persistence between sessions
 * without violating Same-Origin policies.
 */
export default class SandboxEnvironment {
  constructor() {
    // Initialize the Mediator to listen to send messages on the parent of
    // this window (i.e. the iframe parent)
    this.mediator = new Mediator(window.parent);

    this.localStorage = new LocalStorage(this.mediator);

    this.sessionStorage = new SessionStorage(this.mediator);

    this.cookie = new Cookie(this.mediator);

    this.kolibri = new Kolibri(this.mediator);

    this.SCORM = new SCORM(this.mediator);

    // We initialize SCORM here, as the usual place for SCORM
    // to look for its API is window.parent.
    this.SCORM.iframeInitialize(window);

    this.createIframe = this.createIframe.bind(this);

    this.mediator.registerMessageHandler({
      nameSpace,
      event: events.MAINREADY,
      // Get all script tags that have been wrapped in templates
      // by the backend, and then execute them in order.
      // This causes any script execution to be deferred until Hashi has
      // initalized the local environment.
      callback: this.createIframe,
    });

    // Set up a listener for a ready check event.
    this.mediator.registerMessageHandler({
      nameSpace,
      event: events.READYCHECK,
      callback: () => {
        this.mediator.sendMessage({ nameSpace, event: events.IFRAMEREADY, data: true });
      },
    });

    // At this point we are ready, so send the message, in case we misssed the
    // the ready check request.
    this.mediator.sendMessage({ nameSpace, event: events.IFRAMEREADY, data: true });
  }

  initializeIframe(contentWindow) {
    // Only do anything if the contentWindow is the contentWindow of our
    // iframe - this is to prevent other generated iframes from doing anything here.
    if (contentWindow === this.iframe.contentWindow) {
      // Initialize the local storage
      try {
        this.localStorage.iframeInitialize(this.iframe.contentWindow);
        this.sessionStorage.iframeInitialize(this.iframe.contentWindow);
        this.cookie.iframeInitialize(this.iframe.contentWindow);
        this.kolibri.iframeInitialize(this.iframe.contentWindow);
        patchIndexedDB(this.contentNamespace, this.iframe.contentWindow);
      } catch (e) {
        console.log('Shimming storage APIs failed, data will not persist'); // eslint-disable-line no-console
      }
    }
  }

  clearIframe() {
    try {
      this.iframe.contentWindow.removeEventListener('resize', this.resizeIframe);
    } catch (e) {} // eslint-disable-line no-empty
    try {
      document.body.removeChild(this.iframe);
    } catch (e) {} // eslint-disable-line no-empty
  }

  createIframe({ contentNamespace, startUrl = '' } = {}) {
    if (this.iframe) {
      this.clearIframe(this.iframe);
    }
    this.contentNamespace = contentNamespace;
    this.iframe = document.createElement('iframe');
    this.iframe.src = startUrl;
    this.iframe.style.border = 0;
    this.iframe.style.padding = 0;
    this.iframe.style.margin = 0;
    this.iframe.style.position = 'absolute';
    this.iframe.style.width = '100%';
    this.iframe.height = '100%';
    document.body.appendChild(this.iframe);
    this.initializeIframe(this.iframe.contentWindow);
  }
}
