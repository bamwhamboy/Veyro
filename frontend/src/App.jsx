import React, { useEffect, useMemo, useState } from 'react'
import { getAssessment, getEvidence, identifyCheck, submitCheck } from './api.js'

function display(value) {
  return value || 'Not identified from available information'
}

function Identity({ identity }) {
  if (!identity) return <p className="muted">No product identity has been identified yet.</p>
  const rows = [
    ['Brand', identity.brand], ['Product / model', identity.product_name || identity.model_number],
    ['SKU / style code', identity.sku || identity.style_code], ['Colourway', identity.colorway], ['Size', identity.size],
  ].filter(([, value]) => value)
  if (!rows.length) return <p className="muted">No identity details were extracted from the uploaded images.</p>
  return <dl className="identity-grid">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{display(value)}</dd></div>)}</dl>
}

function UploadedPhotos({ photos = [], files = [], evidence = [], guidance = [], missingFields = [] }) {
  const previews = useMemo(() => files.map((file) => (
    typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : null
  )), [files])
  useEffect(() => () => previews.filter(Boolean).forEach((url) => URL.revokeObjectURL(url)), [previews])
  if (!photos.length) return null
  const fieldLabels = {
    brand: 'brand', product_name: 'product/model', model_number: 'model number',
    sku_or_style_code: 'SKU/style code', size: 'size', colorway: 'colourway',
  }
  return <section className="uploaded-photos" aria-label="Uploaded image analysis">
    <div className="uploaded-photos-title"><div><p className="eyebrow">IMAGE CHECKS</p><h3>{photos.length} uploaded image{photos.length === 1 ? '' : 's'}</h3></div><span>{photos.filter((photo) => photo.quality.status === 'good').length} passed quality checks</span></div>
    <ul className="photo-analysis-list">{photos.map((photo, index) => <li className="photo-analysis-item" key={photo.image_id || `${photo.filename}-${index}`}>
      <div className="photo-analysis-content">{previews[index] && <img className="photo-preview" src={previews[index]} alt={`Uploaded ${photo.filename || `image ${index + 1}`}`} />}
      <div className="photo-analysis-details">
      <div className="photo-analysis-heading"><strong>{photo.filename || `Image ${index + 1}`}</strong><span className={`photo-quality ${photo.quality.status === 'good' ? 'is-good' : 'needs-retake'}`}>{photo.quality.status === 'good' ? 'Quality good' : 'Retake recommended'}</span></div>
      <div className="photo-analysis-meta">{photo.quality.width} × {photo.quality.height}px · OCR {photo.ocr_status}</div>
      {photo.quality.issues?.length > 0 && <p className="photo-issues">Image issues: {photo.quality.issues.map((issue) => issue.replaceAll('_', ' ')).join(', ')}</p>}
      {photo.ocr_text
        ? <p className="photo-ocr-text"><b>Text read:</b> {photo.ocr_text}</p>
        : <p className="photo-ocr-text muted">{photo.provider_message || (photo.ocr_status === 'complete' ? 'No readable text found in this image.' : 'Image text was not read.')}</p>}
      <p className="photo-ocr-text"><b>Vision:</b> {photo.vision_status === 'complete' ? 'Analyzed' : photo.vision_message || `Not available (${photo.vision_status})`}</p>
      {photo.vision_evidence_ids?.length > 0 && <ul className="visual-observations">{photo.vision_evidence_ids.map((id) => {
        const item = evidence.find((record) => record.evidence_id === id)
        return item ? <li key={id}><b>{item.subject.replaceAll('_', ' ')}:</b> {item.exact_claim?.split(':').slice(1).join(':').trim() || item.observation}<small>Confidence {Math.round((item.confidence ?? 0) * 100)}% · Evidence {id}</small></li> : null
      })}</ul>}
      </div></div>
    </li>)}</ul>
    {missingFields.length > 0 && <p className="missing-photo-fields"><b>Still unidentified:</b> {missingFields.map((field) => fieldLabels[field] || field.replaceAll('_', ' ')).join(', ')}</p>}
    {guidance.map((message) => <p className="photo-guidance" key={message}>{message}</p>)}
  </section>
}

function Findings({ title, items, emptyText }) {
  return <section className="finding-group"><h3>{title}</h3>{items?.length
    ? <ul>{items.map((item) => <li key={item.finding_id || item.statement}><span>{item.statement}</span><small>{item.dimension} · {item.classification}</small></li>)}</ul>
    : <p className="muted">{emptyText}</p>}</section>
}

function Evidence({ report, assessment }) {
  const evidence = report?.evidence || assessment?.evidence || []
  const sources = report?.evidence_sources || assessment?.evidence_sources || []
  const sourceById = Object.fromEntries(sources.map((source) => [source.source_id, source]))
  if (!evidence.length) return <p className="muted">No evidence is available yet.</p>
  return <div className="evidence-list">{evidence.map((item) => {
    const source = sourceById[item.source_id] || {}
    const url = item.source_url || source.uri
    return <article className="evidence-item" key={item.evidence_id}>
      <div className="evidence-heading"><strong>{source.source_type || item.provider || 'Source'}</strong><span className="trust">{item.source_trust_level || source.trust_level || 'unrated'} trust</span></div>
      {url ? <a href={url} target="_blank" rel="noreferrer">{url}</a> : <span className="muted">No source URL</span>}
      <p><b>Claim:</b> {item.exact_claim || item.observation}</p>
      <small>Retrieved {item.retrieved_at || source.retrieved_at || 'time not recorded'} · {item.provider || source.provider || 'provider not recorded'}</small>
    </article>
  })}</div>
}

export default function App() {
  const [files, setFiles] = useState([])
  const [listingUrl, setListingUrl] = useState('')
  const [sellerName, setSellerName] = useState('')
  const [submission, setSubmission] = useState(null)
  const [identification, setIdentification] = useState(null)
  const [assessment, setAssessment] = useState(null)
  const [evidence, setEvidence] = useState(null)
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setSubmission(null)
    setAssessment(null); setEvidence(null); setIdentification(null)
    if (!files.length) { setError('Choose at least one shoe image.'); return }
    setLoading('Submitting images…')
    try {
      const result = await submitCheck({ files, listingUrl, sellerName })
      setSubmission(result)
    } catch (err) { setError(err.message) }
    finally { setLoading('') }
  }

  async function handleResearch() {
    const checkId = submission?.check?.check_id
    if (!checkId) return
    setError(''); setLoading('Identifying product and gathering web evidence…')
    try {
      const identity = await identifyCheck(checkId)
      const [evidenceReport, assessmentReport] = await Promise.all([getEvidence(checkId), getAssessment(checkId)])
      setIdentification(identity); setEvidence(evidenceReport); setAssessment(assessmentReport)
    } catch (err) { setError(err.message) }
    finally { setLoading('') }
  }

  const candidate = identification?.candidates?.[0]?.identity || submission?.candidate
  const checkId = submission?.check?.check_id
  return <main className="shell">
    <header className="topbar"><a className="brand" href="#top" aria-label="Veyro home">Veyro<span>.</span></a><span>Developer verification workspace</span></header>
    <section className="intro" id="top"><p className="eyebrow">INDIA · FOOTWEAR</p><h1>Check a pair.<br /><em>Follow the evidence.</em></h1><p>Upload photos and optional listing details to inspect identity signals and trace the sources behind the assessment.</p></section>
    <section className="panel submission-panel">
      <div className="section-title"><div><p className="eyebrow">01 / SUBMISSION</p><h2>Product details</h2></div><span className="step-badge">New check</span></div>
      <form onSubmit={handleSubmit}>
        <label className="upload-box"><input aria-label="Shoe images" type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(event) => setFiles(Array.from(event.target.files || []))} /><span className="upload-icon">↑</span><strong>Add shoe photos</strong><small>Use clear views of the shoe, labels, and packaging. Up to 8 images.</small><span className="file-count">{files.length ? `${files.length} image${files.length === 1 ? '' : 's'} selected` : 'JPG, PNG or WebP'}</span></label>
        {files.length > 0 && <ul className="selected-files">{files.map((file) => <li key={`${file.name}-${file.lastModified}`}>{file.name}</li>)}</ul>}
        <div className="form-grid"><label>Product or listing URL <span>Optional</span><input type="url" placeholder="https://…" value={listingUrl} onChange={(event) => setListingUrl(event.target.value)} /></label><label>Seller name <span>Optional</span><input type="text" placeholder="Seller or store name" value={sellerName} onChange={(event) => setSellerName(event.target.value)} /></label></div>
        <button className="primary" type="submit" disabled={Boolean(loading)}>{loading || 'Submit verification'}</button>
      </form>
      {error && <div className="error" role="alert"><strong>Could not complete this step</strong><span>{error}</span></div>}
      {checkId && <div className="submitted-note" role="status"><span>Submission saved</span><code>{checkId}</code></div>}
    </section>

    {submission && <section className="panel results-panel">
      <div className="section-title"><div><p className="eyebrow">02 / RESEARCH</p><h2>Verification report</h2></div><span className="status-pill">{assessment?.overall_assessment?.replaceAll('_', ' ') || 'Research pending'}</span></div>
      <UploadedPhotos photos={submission.photos} files={files} evidence={submission.evidence} guidance={submission.guidance} missingFields={submission.missing_identity_fields} />
      <div className="product-summary"><div><p className="eyebrow">IDENTIFIED PRODUCT</p><h3>{candidate?.product_name || candidate?.model_number || candidate?.brand || 'Awaiting identification'}</h3></div><Identity identity={candidate} /></div>
      {!identification && <button className="primary research-button" onClick={handleResearch} disabled={Boolean(loading)}>{loading || 'Identify product & gather evidence'}</button>}
      {identification && assessment && <>
        <div className="assessment-summary"><div><p className="eyebrow">ASSESSMENT</p><h3>{assessment.overall_assessment.replaceAll('_', ' ')}</h3></div><div className="confidence"><span>Confidence</span><strong>{assessment.confidence}</strong></div><p>{assessment.summary}</p><small>{assessment.confidence_basis}</small></div>
        <div className="findings-grid"><Findings title="Supporting findings" items={assessment.supporting_findings} emptyText="No supporting findings recorded." /><Findings title="Concerns" items={assessment.concerns} emptyText="No concerns recorded." /><Findings title="Contradictions" items={assessment.contradictions} emptyText="No contradictions recorded." /><Findings title="Missing evidence" items={assessment.missing_evidence} emptyText="No missing evidence listed." /></div>
        <details className="evidence-section" open><summary>View Evidence <span>{evidence?.evidence?.length ?? assessment.evidence?.length ?? 0} records</span></summary><Evidence report={evidence} assessment={assessment} /></details>
      </>}
    </section>}
    <footer>Veyro verification is evidence-based and not a guarantee of authenticity.</footer>
  </main>
}
