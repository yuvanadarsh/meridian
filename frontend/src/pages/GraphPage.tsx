import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { HiOutlineXMark } from 'react-icons/hi2'
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from 'react-force-graph-2d'

import { api } from '../api/client'
import type { GraphContactThread, GraphEdge, GraphNode } from '../api/client'

// The force-graph augments our plain node/link records with simulation state
// (x, y, resolved source/target). Alias the library's generics so the canvas
// callbacks stay typed instead of falling back to `any`.
type FGNode = NodeObject<GraphNode>
type FGLink = LinkObject<GraphNode, GraphEdge>

const BACKGROUND = '#080808'

/** After the force engine runs, a link endpoint is the resolved node object. */
function endpointNode(end: FGLink['source']): FGNode | null {
  return end && typeof end === 'object' ? end : null
}

/** Short relative time like "5 min ago" / "2 days ago". */
function formatRelative(iso: string | null): string {
  if (!iso) return ''
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  const days = Math.floor(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

/** Pick a node color from its primary topic, clustering related contacts. */
function topicColor(node: GraphNode): string {
  const topic = (node.topics?.[0] ?? '').toLowerCase()
  if (topic.includes('school') || topic.includes('academic')) return '#34d399'
  if (topic.includes('work') || topic.includes('job') || topic.includes('intern'))
    return '#60a5fa'
  if (topic.includes('housing') || topic.includes('lease')) return '#f59e0b'
  return 'rgba(255,255,255,0.7)'
}

/**
 * /graph — interactive force-directed view of the contact relationship network.
 * Contacts are nodes (sized by email volume), "You" sits at the center, and
 * edges connect contacts who share an email thread. Clicking a node opens a
 * detail panel; search and topic pills dim non-matching nodes.
 */
export function GraphPage() {
  const fgRef =
    useRef<ForceGraphMethods<FGNode, FGLink> | undefined>(undefined)
  const containerRef = useRef<HTMLDivElement>(null)

  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; links: GraphEdge[] }>({
    nodes: [],
    links: [],
  })
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [search, setSearch] = useState('')
  const [activeTopics, setActiveTopics] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState({ totalContacts: 0, totalEdges: 0 })
  const [size, setSize] = useState({ width: 0, height: 0 })

  // Load the graph once on mount.
  useEffect(() => {
    let cancelled = false
    api
      .getGraphData()
      .then((data) => {
        if (cancelled) return
        // react-force-graph expects `links`, the API returns `edges`.
        setGraphData({ nodes: data.nodes, links: data.edges })
        setStats(data.stats)
      })
      .catch(() => {
        // Graph is non-essential; leave the empty-state message on failure.
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Track the canvas container size so the graph fills the space and resizes
  // when the detail panel slides in/out (the panel shrinks the flex-1 column).
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0].contentRect
      setSize({ width: rect.width, height: rect.height })
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // The distinct topics across all contacts, for the filter pills (top 12).
  const allTopics = useMemo(
    () =>
      Array.from(new Set(graphData.nodes.flatMap((n) => n.topics ?? []))).slice(0, 12),
    [graphData.nodes],
  )

  // Node ids that match the current search + topic filter. The user node is
  // always included so the hub stays anchored. When nothing is filtered the set
  // covers every node (so the "is this node dimmed?" check is cheap).
  const filteredNodeIds = useMemo(() => {
    const ids = new Set<string>()
    for (const node of graphData.nodes) {
      const matchesSearch =
        !search ||
        node.label.toLowerCase().includes(search.toLowerCase()) ||
        node.email.toLowerCase().includes(search.toLowerCase())
      const matchesTopic =
        activeTopics.length === 0 || activeTopics.some((t) => node.topics?.includes(t))
      if (matchesSearch && matchesTopic) ids.add(node.id)
    }
    ids.add('user')
    return ids
  }, [graphData.nodes, search, activeTopics])

  const isFiltering = search !== '' || activeTopics.length > 0

  const handleNodeClick = useCallback((node: FGNode) => {
    if (node.type === 'user') return
    setSelectedNode(node as GraphNode)
    fgRef.current?.centerAt(node.x, node.y, 500)
    fgRef.current?.zoom(2, 500)
  }, [])

  // Draw each node: size by email volume, color by topic, with labels only at
  // zoom or for high-volume nodes to avoid clutter. Dimmed when filtered out.
  const nodeCanvasObject = useCallback(
    (node: FGNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const isUser = node.type === 'user'
      const isSelected = selectedNode?.id === node.id
      const isDimmed = isFiltering && !filteredNodeIds.has(String(node.id))

      const size = isUser
        ? 14
        : Math.max(4, Math.min(12, 3 + Math.sqrt(node.emailCount || 1) * 0.8))

      let color: string
      if (isUser) color = '#6366f1'
      else if (isDimmed) color = 'rgba(255,255,255,0.1)'
      else if (isSelected) color = '#f97316'
      else color = topicColor(node)

      ctx.beginPath()
      ctx.arc(node.x ?? 0, node.y ?? 0, size, 0, 2 * Math.PI)
      ctx.fillStyle = color
      ctx.fill()

      if (isSelected) {
        ctx.beginPath()
        ctx.arc(node.x ?? 0, node.y ?? 0, size + 3, 0, 2 * Math.PI)
        ctx.strokeStyle = '#f97316'
        ctx.lineWidth = 1.5
        ctx.stroke()
      }

      const showLabel =
        globalScale > 1.5 || node.emailCount > 30 || isUser || isSelected
      if (showLabel && !isDimmed) {
        const fontSize = Math.max(8, 11 / globalScale)
        ctx.font = `${fontSize}px Inter, sans-serif`
        ctx.fillStyle = 'rgba(255,255,255,0.85)'
        ctx.textAlign = 'center'
        ctx.fillText(node.label, node.x ?? 0, (node.y ?? 0) + size + fontSize + 1)
      }
    },
    [selectedNode, filteredNodeIds, isFiltering],
  )

  // Draw each edge, faint by default and nearly invisible when either endpoint
  // is filtered out so the matching subgraph reads clearly.
  const linkCanvasObject = useCallback(
    (link: FGLink, ctx: CanvasRenderingContext2D) => {
      const src = endpointNode(link.source)
      const tgt = endpointNode(link.target)
      if (!src || !tgt) return

      const eitherFiltered =
        isFiltering &&
        (!filteredNodeIds.has(String(src.id)) || !filteredNodeIds.has(String(tgt.id)))

      ctx.globalAlpha = eitherFiltered ? 0.02 : Math.min(0.6, 0.1 + link.weight * 0.05)
      ctx.beginPath()
      ctx.moveTo(src.x ?? 0, src.y ?? 0)
      ctx.lineTo(tgt.x ?? 0, tgt.y ?? 0)
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = Math.min(2, 0.5 + link.weight * 0.1)
      ctx.stroke()
      ctx.globalAlpha = 1
    },
    [filteredNodeIds, isFiltering],
  )

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-white/30">Loading knowledge graph…</div>
      </div>
    )
  }

  return (
    <div className="relative flex h-full overflow-hidden">
      {/* Graph canvas column — shrinks when the detail panel is open. */}
      <div ref={containerRef} className="relative flex-1">
        {/* Search + topic filters, top-right overlay. */}
        <div className="absolute right-4 top-4 z-10 flex flex-col items-end gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search contacts…"
            className="w-52 rounded-xl border border-white/10 bg-black/60 px-3 py-2 text-sm text-white placeholder-white/30 outline-none backdrop-blur"
          />
          <div className="flex max-w-xs flex-wrap justify-end gap-1">
            {allTopics.map((topic) => (
              <button
                key={topic}
                onClick={() =>
                  setActiveTopics((prev) =>
                    prev.includes(topic)
                      ? prev.filter((t) => t !== topic)
                      : [...prev, topic],
                  )
                }
                className={`rounded-full border px-2 py-0.5 text-xs transition-colors ${
                  activeTopics.includes(topic)
                    ? 'border-white/40 bg-white/20 text-white'
                    : 'border-white/10 bg-black/40 text-white/40 hover:text-white/60'
                }`}
              >
                {topic}
              </button>
            ))}
          </div>
        </div>

        {/* Stats, bottom-left overlay. */}
        <div className="absolute bottom-4 left-4 z-10 text-xs text-white/30">
          {stats.totalContacts} contacts · {stats.totalEdges} connections
          {activeTopics.length > 0 && ` · filtered by ${activeTopics.join(', ')}`}
        </div>

        <ForceGraph2D
          ref={fgRef}
          width={size.width}
          height={size.height}
          graphData={graphData}
          backgroundColor={BACKGROUND}
          nodeCanvasObject={nodeCanvasObject}
          nodeCanvasObjectMode={() => 'replace'}
          linkCanvasObject={linkCanvasObject}
          linkCanvasObjectMode={() => 'replace'}
          onNodeClick={handleNodeClick}
          onBackgroundClick={() => setSelectedNode(null)}
          nodeLabel={(node) => (node as GraphNode).label}
          cooldownTicks={100}
          onEngineStop={() => fgRef.current?.zoomToFit(400, 80)}
          d3AlphaDecay={0.02}
          d3VelocityDecay={0.3}
        />
      </div>

      {selectedNode && (
        <ContactDetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />
      )}
    </div>
  )
}

/** Right-hand panel with a contact's stats, topics, and recent threads. */
function ContactDetailPanel({
  node,
  onClose,
}: {
  node: GraphNode
  onClose: () => void
}) {
  const [threads, setThreads] = useState<GraphContactThread[]>([])
  const navigate = useNavigate()
  const contactId = Number(node.id.replace('contact_', ''))

  useEffect(() => {
    let cancelled = false
    api
      .getContactThreads(contactId)
      .then((rows) => {
        if (!cancelled) setThreads(rows)
      })
      .catch(() => {
        if (!cancelled) setThreads([])
      })
    return () => {
      cancelled = true
    }
  }, [contactId])

  return (
    <motion.div
      initial={{ x: 400 }}
      animate={{ x: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="flex h-full w-[400px] flex-col overflow-hidden border-l border-white/5 bg-[#0a0a0a]"
    >
      <div className="flex items-center justify-between border-b border-white/5 px-6 py-4">
        <div className="min-w-0">
          <div className="truncate font-medium text-white">{node.label}</div>
          <div className="mt-0.5 truncate text-xs text-white/40">{node.email}</div>
        </div>
        <button onClick={onClose} className="text-white/30 hover:text-white">
          <HiOutlineXMark className="h-5 w-5" />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 border-b border-white/5 px-6 py-4">
        <div className="rounded-xl bg-white/[0.03] p-3">
          <div className="text-xl font-semibold text-white">{node.emailCount}</div>
          <div className="mt-0.5 text-xs text-white/40">Total emails</div>
        </div>
        <div className="rounded-xl bg-white/[0.03] p-3">
          <div className="text-xl font-semibold text-white">{node.sentCount}</div>
          <div className="mt-0.5 text-xs text-white/40">You sent</div>
        </div>
      </div>

      {node.topics.length > 0 && (
        <div className="border-b border-white/5 px-6 py-3">
          <div className="mb-2 text-xs text-white/40">Topics</div>
          <div className="flex flex-wrap gap-1">
            {node.topics.map((topic) => (
              <span
                key={topic}
                className="rounded-full bg-white/[0.08] px-2 py-0.5 text-xs text-white/60"
              >
                {topic}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-6 py-3">
        <div className="mb-3 text-xs text-white/40">Recent threads</div>
        {threads.length === 0 ? (
          <div className="text-xs text-white/20">No threads found</div>
        ) : (
          <div className="space-y-2">
            {threads.map((thread) => (
              <div
                key={thread.id}
                className="rounded-xl border border-white/5 bg-white/[0.03] p-3"
              >
                <div className="line-clamp-2 text-xs font-medium text-white/80">
                  {thread.subject || '(no subject)'}
                </div>
                <div className="mt-1 text-xs text-white/30">
                  {thread.message_count} messages
                  {thread.last_message_at &&
                    ` · ${formatRelative(thread.last_message_at)}`}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="border-t border-white/5 px-6 py-4">
        <button
          onClick={() => navigate(`/contacts?search=${encodeURIComponent(node.email)}`)}
          className="w-full text-center text-xs text-white/40 transition-colors hover:text-white/60"
        >
          View in Contacts →
        </button>
      </div>
    </motion.div>
  )
}

export default GraphPage
