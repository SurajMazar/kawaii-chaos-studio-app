import { Alert, Col, Row, Typography } from 'antd'
import TextEditor from '../components/TextEditor'
import type { TabProps } from '../pages/PiecePage'

export default function ScriptTab({ kind, id, reload }: TabProps) {
  return (
    <Row gutter={16}>
      <Col span={24}>
        <Alert className="!mb-3" type="info" showIcon message={kind === 'strip'
          ? <span>Line 1 is the title (<code># name — "Title" (Couple, mood)</code>). Then the panels as <b>1. 2. 3. …</b> — one short line each: panel 1 states the premise, the last panel pays it off. The <b>**Caption:**</b>, <b>**Pinned comment:**</b> and <b>**Song ideas**</b> lines are used by the Post tab.</span>
          : <span>Music videos must be a <b>new</b> story — never a scene or joke from an existing strip or reel. Note the song, the frames and the timing idea here.</span>} />
        <TextEditor kind={kind} id={id} name="synopsis.md" onSaved={reload} />
        <Typography.Paragraph type="secondary" className="!mt-2 text-xs">Every save keeps the old version in <code>.studio_history/</code> inside this project folder.</Typography.Paragraph>
      </Col>
    </Row>
  )
}
