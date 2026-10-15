import {
  CompaniesWorkspace,
  type CompanySearch,
} from "../../../components/agent-workspace/companies-workspace";
export default async function TenantsPage({
  searchParams,
}: {
  searchParams?: Promise<CompanySearch>;
}) {
  return CompaniesWorkspace({ search: await searchParams });
}
