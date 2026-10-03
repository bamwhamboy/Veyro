import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App.jsx'

const checkId = 'check-123'
const assessment = {
  overall_assessment: 'inconclusive', confidence: 'low', confidence_basis: 'Only partial identity evidence is available.',
  summary: 'The product could not be conclusively assessed.', supporting_findings: [], concerns: [], contradictions: [],
  missing_evidence: [{ finding_id: 'missing-1', dimension: 'SKU', classification: 'unknown', statement: 'A clear SKU photo is missing.' }],
  evidence: [{ evidence_id: 'ev-1', source_id: 'src-1', exact_claim: 'Nike Pegasus 41', source_url: 'https://brand.example/item', source_trust_level: 'very_high', retrieved_at: '2026-10-03T09:00:00Z' }],
  evidence_sources: [{ source_id: 'src-1', source_type: 'official_brand', uri: 'https://brand.example/item', trust_level: 'very_high', provider: 'mock' }],
}

beforeEach(() => vi.restoreAllMocks())

describe('verification flow', () => {
  it('submits multiple images, researches, and displays the explainable report', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options = {}) => {
      if (String(url).endsWith('/v1/authenticity/checks') && options.method === 'POST') {
        const body = options.body
        expect(body.getAll('photos')).toHaveLength(2)
        expect(JSON.parse(body.get('metadata'))).toMatchObject({ listing_url: null, seller_name: null })
        return Response.json({
          check: { check_id: checkId }, candidate: { brand: 'Nike', model_number: 'Pegasus 41' },
          photos: [{ image_id: 'photo-1', filename: 'shoe-front.png', quality: { status: 'good', width: 800, height: 600, issues: [] }, ocr_status: 'unavailable', vision_status: 'complete', vision_evidence_ids: ['visual-1'] }],
          evidence: [{ evidence_id: 'visual-1', subject: 'brand', exact_claim: 'brand: Nike', confidence: 0.93 }],
          guidance: [], missing_identity_fields: [],
        })
      }
      if (String(url).endsWith('/identify')) return Response.json({ candidates: [{ identity: { brand: 'Nike', product_name: 'Pegasus 41' } }] })
      if (String(url).endsWith('/evidence')) return Response.json({ evidence: assessment.evidence, evidence_sources: assessment.evidence_sources })
      if (String(url).endsWith('/assessment')) return Response.json(assessment)
      throw new Error(`Unexpected request ${url}`)
    })
    render(<App />)
    const input = screen.getByLabelText('Shoe images')
    fireEvent.change(input, { target: { files: [new File(['one'], 'shoe-front.png', { type: 'image/png' }), new File(['two'], 'label.png', { type: 'image/png' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Submit verification' }))
    await screen.findByText(checkId)
    expect(screen.getByText(/brand:/)).toBeInTheDocument()
    expect(screen.getAllByText('Nike').length).toBeGreaterThan(0)
    expect(screen.getByText('Confidence 93% · Evidence visual-1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Identify product & gather evidence' }))
    await waitFor(() => expect(screen.getAllByText('Nike').length).toBeGreaterThan(0))
    expect(await screen.findByRole('heading', { name: 'inconclusive' })).toBeInTheDocument()
    expect(screen.getByText('Only partial identity evidence is available.')).toBeInTheDocument()
    expect(screen.getByText('A clear SKU photo is missing.')).toBeInTheDocument()
    expect(screen.getByText('Nike Pegasus 41')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })

  it('shows a useful upload validation message', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Submit verification' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose at least one shoe image.')
  })

  it('shows API errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ detail: 'Search is not configured' }, { status: 503 }))
    render(<App />)
    fireEvent.change(screen.getByLabelText('Shoe images'), { target: { files: [new File(['one'], 'shoe.png', { type: 'image/png' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Submit verification' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Search is not configured')
  })
})
