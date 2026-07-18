<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // Per-task OS-resource snapshots (devharness.health). Process / git / worktree / memory growth makes
  // the leak class visible before it bites: a climbing git count = orphaned fsmonitor daemons, which
  // is what tripped the Agent SDK's init timeout during the jqlite drive. -1 means a probe failed.
  let feed = $state([]);
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    feed = [
      ...feed,
      {
        received_at: msg.received_at,
        procs: p.process_count,
        git: p.git_process_count,
        wt: p.worktree_count,
        mem: p.free_memory_mb,
      },
    ].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(['resource_snapshot'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Resource Health</h2>
  <small>resource_snapshot · procs · git · worktrees · free MB</small>
  {#if feed.length === 0}
    <p>no resource snapshots yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each feed as e, i (i)}
        <li>
          <span class="ts">{fmtTime(e.received_at)}</span>
          {e.procs} procs · <span class:warn={e.git > 50}>{e.git} git</span> · {e.wt} wt · {e.mem}MB
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .warn {
    color: #b91c1c;
    font-weight: 600;
  }
</style>
