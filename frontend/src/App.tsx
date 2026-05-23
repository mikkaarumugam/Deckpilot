/**
 * App — outermost mount point. Renders <Pilot/>.
 *
 * Kept minimal so future top-level concerns (theme context, query client,
 * error boundary) have a clean place to live without restructuring.
 */

import { Pilot } from './Pilot';

export default function App() {
  return <Pilot />;
}
