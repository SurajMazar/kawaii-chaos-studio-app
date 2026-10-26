import { useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// links rendered from markdown open safely in a new tab (no window.opener)
DOMPurify.addHook('afterSanitizeAttributes', node => {
  if (node.tagName === 'A') { node.setAttribute('target', '_blank'); node.setAttribute('rel', 'noopener noreferrer') }
})

/** Renders the repo's own markdown (synopsis, qa.md). Raw HTML in the source is escaped, and the generated HTML is
 *  sanitised with DOMPurify (no scripts, event handlers or javascript: links — the files can be edited by any editor). */
export default function Markdown({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => {
    const safe = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/^&gt;/gm, '>')
    const raw = marked.parse(safe, { async: false, gfm: true, breaks: true }) as string
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true }, FORBID_TAGS: ['style', 'form', 'input', 'iframe'], ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|#|\/)/i })
  }, [text])
  return <div className={`md ${className ?? ''}`} dangerouslySetInnerHTML={{ __html: html }} />
}
