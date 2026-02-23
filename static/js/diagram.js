/* Column Lineage Diagram Engine – D3.js v7 */
const DiagramEngine = (() => {
  const CFG = {
    nodeW:      220,
    headerH:    36,
    rowH:       22,
    layerGap:   290,
    nodeGap:    28,
    edgeColors: {
      direct:    '#64748B',
      computed:  '#6366F1',
      aggregate: '#F97316',
      concat:    '#A855F7',
      case:      '#EC4899'
    },
    edgeDash: {
      computed:  '5,3',
      aggregate: '3,3',
      case:      '7,3'
    }
  };

  let svg, mainG, zoomBehavior, nodes, edges, showEdgeLabels = true;
  let selectedCol = null;   // { nodeId, colName } when pinned, else null

  // ── INIT ─────────────────────────────────────────────────────
  function init(selector, graphData) {
    nodes = graphData.nodes.map(n => Object.assign({}, n));
    edges = graphData.edges.map(e => Object.assign({}, e));

    const el = document.querySelector(selector);
    el.innerHTML = '';

    svg = d3.select(selector);

    // Arrowhead markers
    const defs = svg.append('defs');
    Object.entries(CFG.edgeColors).forEach(([type, color]) => {
      defs.append('marker')
        .attr('id', `arr-${type}`)
        .attr('viewBox', '0 -4 8 8')
        .attr('refX', 8).attr('refY', 0)
        .attr('markerWidth', 5).attr('markerHeight', 5)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-4L8,0L0,4Z')
        .attr('fill', color);
    });

    mainG = svg.append('g').attr('class', 'main-g');

    zoomBehavior = d3.zoom()
      .scaleExtent([0.04, 4])
      .on('zoom', e => mainG.attr('transform', e.transform));
    svg.call(zoomBehavior);

    // Click on blank canvas → clear selection
    svg.on('click', function(e) {
      if (e.target === this || e.target.tagName === 'svg') clearSelection();
    });

    computeLayout();
    renderEdges();
    renderNodes();
    renderLegend();
    setTimeout(fitView, 80);
  }

  // ── LAYOUT ───────────────────────────────────────────────────
  function computeLayout() {
    const adj = {}, inDeg = {};
    nodes.forEach(n => { adj[n.id] = new Set(); inDeg[n.id] = 0; });

    // Build node-level adjacency (deduplicated)
    const seen = new Set();
    edges.forEach(e => {
      const k = e.source_node + '→' + e.target_node;
      if (!seen.has(k) && adj[e.source_node] !== undefined && adj[e.target_node] !== undefined) {
        seen.add(k);
        adj[e.source_node].add(e.target_node);
        inDeg[e.target_node]++;
      }
    });

    // BFS topological layering
    const layer = {};
    const queue = nodes.filter(n => !inDeg[n.id]).map(n => n.id);
    queue.forEach(id => { layer[id] = 0; });

    let qi = 0;
    while (qi < queue.length) {
      const cur = queue[qi++];
      (adj[cur] || new Set()).forEach(nxt => {
        layer[nxt] = Math.max(layer[nxt] || 0, (layer[cur] || 0) + 1);
        if (--inDeg[nxt] === 0) queue.push(nxt);
      });
    }

    // Nodes without any layer assignment (isolated)
    nodes.forEach(n => { if (layer[n.id] === undefined) layer[n.id] = 0; });

    // Group by layer
    const byLayer = {};
    nodes.forEach(n => {
      const l = layer[n.id];
      if (!byLayer[l]) byLayer[l] = [];
      byLayer[l].push(n);
    });

    // Assign positions
    const typeOrder = { table: 0, view: 1, procedure: 2 };
    Object.keys(byLayer).sort((a, b) => +a - +b).forEach(l => {
      const grp = byLayer[l];
      grp.sort((a, b) => (typeOrder[a.type] || 0) - (typeOrder[b.type] || 0));
      let y = 40;
      grp.forEach(n => {
        n.x = +l * CFG.layerGap + 40;
        n.y = y;
        n.height = CFG.headerH + n.columns.length * CFG.rowH + 4;
        y += n.height + CFG.nodeGap;
      });
    });
  }

  // ── NODE RENDERING ───────────────────────────────────────────
  function renderNodes() {
    const nodesById = {};
    nodes.forEach(n => nodesById[n.id] = n);

    const typeColor = { table: '#1D4ED8', view: '#15803D', procedure: '#C2410C' };
    const typeBg    = { table: '#1E3A5F', view: '#14432A', procedure: '#431407' };

    const grps = mainG.selectAll('.node')
      .data(nodes, d => d.id)
      .join('g')
      .attr('class', d => `node node-${d.type}`)
      .attr('id', d => `node-${d.id}`)
      .attr('transform', d => `translate(${d.x},${d.y})`)
      .call(d3.drag()
        .on('start', function(e, d) { d3.select(this).raise(); })
        .on('drag', function(e, d) {
          d.x += e.dx; d.y += e.dy;
          d3.select(this).attr('transform', `translate(${d.x},${d.y})`);
          updateEdgePaths();
        })
      );

    // Drop shadow
    grps.append('rect')
      .attr('x', 3).attr('y', 4)
      .attr('width', CFG.nodeW).attr('height', d => d.height)
      .attr('rx', 7).attr('fill', 'rgba(0,0,0,0.4)');

    // Body background
    grps.append('rect')
      .attr('class', 'node-body-rect')
      .attr('width', CFG.nodeW).attr('height', d => d.height)
      .attr('rx', 7);

    // Header background
    grps.append('rect')
      .attr('width', CFG.nodeW).attr('height', CFG.headerH)
      .attr('rx', 7)
      .attr('fill', d => typeColor[d.type] || '#475569');

    // Flatten top corners of header bottom (to make it look flush)
    grps.append('rect')
      .attr('y', CFG.headerH / 2)
      .attr('width', CFG.nodeW).attr('height', CFG.headerH / 2)
      .attr('fill', d => typeColor[d.type] || '#475569');

    // Type badge (top-right)
    grps.append('text')
      .attr('x', CFG.nodeW - 8).attr('y', 12)
      .attr('text-anchor', 'end')
      .attr('font-size', 8).attr('font-weight', '600')
      .attr('fill', 'rgba(255,255,255,0.6)')
      .attr('letter-spacing', '0.5')
      .text(d => d.type.toUpperCase());

    // Node name
    grps.append('text')
      .attr('x', 10).attr('y', CFG.headerH - 9)
      .attr('font-size', 12).attr('font-weight', '700').attr('fill', 'white')
      .text(d => d.label.length > 25 ? d.label.slice(0, 24) + '…' : d.label)
      .append('title').text(d => d.label);

    // Column rows
    grps.each(function(nd) {
      const g = d3.select(this);
      nd.columns.forEach((col, i) => {
        const ry = CFG.headerH + i * CFG.rowH;
        const row = g.append('g')
          .attr('class', 'col-row')
          .attr('data-node', nd.id)
          .attr('data-col', col.name)
          .attr('transform', `translate(0,${ry})`);

        row.append('rect')
          .attr('class', i % 2 === 0 ? 'col-bg' : 'col-bg alt')
          .attr('width', CFG.nodeW).attr('height', CFG.rowH);
          // fill controlled by CSS variables (--bg-node / --bg-node-alt) for theme support

        if (col.is_pk) {
          row.append('text').attr('class', 'col-pk').attr('x', 7).attr('y', 15).text('⚷');
        }

        row.append('text')
          .attr('class', 'col-name')
          .attr('x', col.is_pk ? 20 : 9).attr('y', 15)
          .text(col.name);

        row.append('text')
          .attr('class', 'col-type')
          .attr('x', CFG.nodeW - 7).attr('y', 15)
          .attr('text-anchor', 'end')
          .text(col.data_type);

        // Click to pin selection; hover only shows cursor cue (CSS handles bg)
        row.on('click', (e) => {
          e.stopPropagation();
          if (selectedCol && selectedCol.nodeId === nd.id && selectedCol.colName === col.name) {
            clearSelection();   // click same column again → deselect
          } else {
            selectColumn(nd.id, col.name);
          }
        });
      });

      // Bottom border
      if (nd.columns.length > 0) {
        g.append('line')
          .attr('x1', 0).attr('x2', CFG.nodeW)
          .attr('y1', nd.height).attr('y2', nd.height)
          .attr('stroke', '#334155').attr('stroke-width', 1);
      }
    });
  }

  // ── EDGE RENDERING ───────────────────────────────────────────
  function colAnchor(nodeId, colName, side) {
    const n = nodes.find(x => x.id === nodeId);
    if (!n) return { x: 0, y: 0 };
    const ci = n.columns.findIndex(c => c.name === colName);
    const y = n.y + CFG.headerH + (ci >= 0 ? ci : 0) * CFG.rowH + CFG.rowH / 2;
    return { x: side === 'right' ? n.x + CFG.nodeW : n.x, y };
  }

  function edgePath(e) {
    const s = colAnchor(e.source_node, e.source_column, 'right');
    const t = colAnchor(e.target_node, e.target_column, 'left');
    const dx = Math.abs(t.x - s.x) * 0.55;
    return `M${s.x},${s.y} C${s.x + dx},${s.y} ${t.x - dx},${t.y} ${t.x},${t.y}`;
  }

  function renderEdges() {
    mainG.selectAll('.edge')
      .data(edges, d => d.id)
      .join('path')
      .attr('class', d => `edge edge-${d.edge_type}`)
      .attr('id', d => `edge-${d.id}`)
      .attr('d', edgePath)
      .attr('fill', 'none')
      .attr('stroke', d => CFG.edgeColors[d.edge_type] || '#64748B')
      .attr('stroke-width', 1.4)
      .attr('stroke-dasharray', d => CFG.edgeDash[d.edge_type] || null)
      .attr('opacity', null)          // CSS var(--edge-opacity) drives default
      .attr('marker-end', d => `url(#arr-${d.edge_type})`)
      .on('mouseenter', function(e, d) {
        if (!selectedCol) {
          d3.select(this).attr('stroke-width', 2.8).attr('opacity', 1);
        }
        showTooltip(e, `<span class="tt-type">${d.edge_type}</span><br><strong>${d.source_node}</strong>.${d.source_column}<br>→ <strong>${d.target_node}</strong>.${d.target_column}`);
      })
      .on('mouseleave', function(e, d) {
        if (!selectedCol) {
          d3.select(this).attr('stroke-width', 1.4).attr('opacity', 0.55);
        }
        hideTooltip();
      });
  }

  function updateEdgePaths() {
    mainG.selectAll('.edge').attr('d', edgePath);
  }

  // ── SELECTION (click-to-pin) ──────────────────────────────────
  function selectColumn(nodeId, colName) {
    selectedCol = { nodeId, colName };

    const connEdges = new Set();
    const connCols  = new Set([`${nodeId}::${colName}`]);

    // BFS upstream (all hops)
    let front = [`${nodeId}::${colName}`];
    for (let i = 0; i < 30 && front.length; i++) {
      const next = [];
      front.forEach(k => {
        const [nId, col] = k.split('::');
        edges.filter(e => e.target_node === nId && e.target_column === col).forEach(e => {
          connEdges.add(e.id);
          const nk = `${e.source_node}::${e.source_column}`;
          if (!connCols.has(nk)) { connCols.add(nk); next.push(nk); }
        });
      });
      front = next;
    }

    // BFS downstream (all hops)
    front = [`${nodeId}::${colName}`];
    for (let i = 0; i < 30 && front.length; i++) {
      const next = [];
      front.forEach(k => {
        const [nId, col] = k.split('::');
        edges.filter(e => e.source_node === nId && e.source_column === col).forEach(e => {
          connEdges.add(e.id);
          const nk = `${e.target_node}::${e.target_column}`;
          if (!connCols.has(nk)) { connCols.add(nk); next.push(nk); }
        });
      });
      front = next;
    }

    // Apply visual styles
    mainG.selectAll('.edge')
      .attr('opacity', d => connEdges.has(d.id) ? 1 : 0.05)
      .attr('stroke-width', d => connEdges.has(d.id) ? 2.8 : 1.4);

    mainG.selectAll('.col-row')
      .classed('dimmed', function() {
        return !connCols.has(this.dataset.node + '::' + this.dataset.col);
      })
      .classed('highlighted', function() {
        const k = this.dataset.node + '::' + this.dataset.col;
        return connCols.has(k) && k !== `${nodeId}::${colName}`;
      })
      .classed('current', function() {
        return this.dataset.node === nodeId && this.dataset.col === colName;
      });

    // Build direct sources and targets for the info bar
    const colObj    = nodes.find(n => n.id === nodeId)?.columns.find(c => c.name === colName);
    const objectType = nodes.find(n => n.id === nodeId)?.type || 'table';

    const directSources = edges
      .filter(e => e.target_node === nodeId && e.target_column === colName)
      .map(e => ({
        nodeId: e.source_node, colName: e.source_column,
        objectType: nodes.find(n => n.id === e.source_node)?.type || 'table',
        edgeType: e.edge_type
      }));

    const directTargets = edges
      .filter(e => e.source_node === nodeId && e.source_column === colName)
      .map(e => ({
        nodeId: e.target_node, colName: e.target_column,
        objectType: nodes.find(n => n.id === e.target_node)?.type || 'view',
        edgeType: e.edge_type
      }));

    // Fire event so the info bar can update
    document.dispatchEvent(new CustomEvent('lineage-selected', {
      detail: {
        nodeId, colName,
        dataType:   colObj?.data_type || '',
        objectType,
        sources:    directSources,
        targets:    directTargets,
        totalConnected: connCols.size - 1
      }
    }));
  }

  function reapplyColors() {
    if (!mainG) return;
    mainG.selectAll('.edge').attr('opacity', null).attr('stroke-width', 1.4);
  }

  function clearSelection() {
    selectedCol = null;
    mainG.selectAll('.edge').attr('opacity', null).attr('stroke-width', 1.4);
    mainG.selectAll('.col-row').classed('dimmed', false).classed('highlighted', false).classed('current', false);
    hideTooltip();
    document.dispatchEvent(new CustomEvent('lineage-cleared'));
  }

  // ── ZOOM ─────────────────────────────────────────────────────
  function fitView() {
    if (!nodes || !nodes.length) return;
    const xs = nodes.map(n => n.x), ys = nodes.map(n => n.y);
    const x2s = nodes.map(n => n.x + CFG.nodeW), y2s = nodes.map(n => n.y + n.height);
    const minX = Math.min(...xs) - 30, minY = Math.min(...ys) - 30;
    const maxX = Math.max(...x2s) + 30, maxY = Math.max(...y2s) + 30;
    const el = svg.node();
    const W = el.clientWidth || 1200, H = el.clientHeight || 700;
    const sc = Math.min(W / (maxX - minX), H / (maxY - minY), 0.95);
    const tx = (W - sc * (maxX - minX)) / 2 - sc * minX;
    const ty = (H - sc * (maxY - minY)) / 2 - sc * minY;
    svg.transition().duration(500)
      .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(sc));
  }

  function resetView() { fitView(); }

  function zoomBy(factor) {
    svg.transition().duration(200).call(zoomBehavior.scaleBy, factor);
  }

  // ── FILTER ───────────────────────────────────────────────────
  function filter(term) {
    if (!term) {
      mainG.selectAll('.node').classed('hidden', false);
      mainG.selectAll('.edge').classed('hidden', false);
      return;
    }
    const t = term.toLowerCase();
    const matchNodes = new Set();
    nodes.forEach(n => {
      if (n.id.toLowerCase().includes(t) || n.columns.some(c => c.name.toLowerCase().includes(t)))
        matchNodes.add(n.id);
    });
    mainG.selectAll('.node').classed('hidden', d => !matchNodes.has(d.id));
    mainG.selectAll('.edge').classed('hidden', d =>
      !matchNodes.has(d.source_node) || !matchNodes.has(d.target_node)
    );
  }

  function toggleEdgeLabels(show) {
    showEdgeLabels = show;
  }

  // ── LEGEND ───────────────────────────────────────────────────
  function renderLegend() {
    // Remove existing
    d3.select('.legend').remove();

    const legend = d3.select('body').append('div').attr('class', 'legend');
    legend.append('h4').text('Object Types');

    [['table','#1D4ED8','Table'],['view','#15803D','View'],['procedure','#C2410C','Stored Proc']].forEach(([,color,label]) => {
      const item = legend.append('div').attr('class','legend-item');
      item.append('div').attr('class','legend-dot').style('background', color);
      item.append('span').text(label);
    });

    legend.append('h4').style('margin-top','10px').text('Edge Types');
    Object.entries(CFG.edgeColors).forEach(([type, color]) => {
      const item = legend.append('div').attr('class','legend-item');
      item.append('div').attr('class','legend-line').style('background',color)
        .style('border-top', CFG.edgeDash[type] ? `2px dashed ${color}` : `2px solid ${color}`)
        .style('background','none').style('height','0').style('margin-top','5px');
      item.append('span').text(type.charAt(0).toUpperCase() + type.slice(1));
    });
  }

  // ── TOOLTIP ──────────────────────────────────────────────────
  const tt = () => document.getElementById('tooltip');

  function showTooltip(e, html) {
    const el = tt(); if (!el) return;
    el.innerHTML = html;
    el.classList.add('visible');
    const x = e.clientX || e.pageX, y = e.clientY || e.pageY;
    el.style.left = (x + 14) + 'px';
    el.style.top  = (y - 36) + 'px';
  }

  function hideTooltip() {
    const el = tt(); if (el) el.classList.remove('visible');
  }

  return { init, filter, resetView, fitView, zoomBy, toggleEdgeLabels, selectColumn, clearSelection, reapplyColors };
})();
