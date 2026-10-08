import { Link } from "react-router-dom";
import { Empty } from "../components/ui";

export function NotFound() {
  return (
    <>
      <h1 className="sr-only">Page not found</h1>
      <div className="panel">
        <Empty title="Page not found">
          There is no page at this address. <Link to="/cases">Go to the case files</Link>.
        </Empty>
      </div>
    </>
  );
}
